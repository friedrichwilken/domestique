"""The web console's HTTP application.

``create_app`` takes the settings and, for tests, providers for the report,
the day view, the open questions, today's date and the claims store; each one left out reads the
database (read-only for the report and the day view) or the config. Routes:

- ``GET /healthz``: ``{"ok": true}``
- ``GET /claims.json``: the report as JSON, every scored prediction
- ``GET /claims``: the claims report page; ``?shadows=0`` hides shadow predictions
- ``GET /day``: redirect to today in the configured timezone
- ``GET /day/{date}`` and ``GET /day/{date}.json``: rails, plan versus execution, open questions
- ``GET /questions.json``: every open question for the athlete, text unchanged
- ``GET /claims/{id}/history.json``: the claim's history rows from the claims store
- ``POST /claims/{id}/decide`` (form: ``status``, ``reason``, ``token``) and
  ``POST /claims/{id}/clear-flags`` (form: ``reason``, ``token``): the human gate.
  The token is read from the form body only and checked by
  ``domestique.claims.gate.require_human``, the same check as the MCP server.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from domestique import config, db
from domestique.claims.gate import HumanTokenError, require_human
from domestique.claims.rules import Status
from domestique.claims.store import ClaimNotFoundError, ClaimsStore, PgStore
from domestique.ingest.settings import cli_settings
from domestique.replay.pg import open_readonly
from domestique.web import day as day_view
from domestique.web.pages import claims_page, day_page
from domestique.web.queries import ReportData, as_json, from_db, history_json

type ReportProvider = Callable[[], ReportData]
type DayProvider = Callable[[date], day_view.DayView]
type QuestionsProvider = Callable[[], Sequence[day_view.OpenQuestion]]
type TodayProvider = Callable[[], date]
type StoreProvider = Callable[[], AbstractContextManager[ClaimsStore]]

DECIDED_BY = "console"  # the ``by`` of every history row the human gate writes from here
DECISIONS = frozenset({Status.ACTIVE.value, Status.RETIRED.value})


@dataclass(frozen=True)
class WebSettings:
    athlete_id: str
    dsn: str | None  # None: db.connect's default (DOMESTIQUE_DSN or the local compose database)


def settings_from_env(env: Mapping[str, str] | None = None) -> WebSettings:
    """Athlete id and database URL by the same rules as the CLIs (``ingest.settings``)."""
    athlete_id, dsn = cli_settings(os.environ if env is None else env)
    return WebSettings(athlete_id, dsn)


def db_provider(settings: WebSettings) -> ReportProvider:
    def provide() -> ReportData:
        with open_readonly(settings.dsn) as conn:
            return from_db(conn, settings.athlete_id)

    return provide


def db_day_provider(settings: WebSettings) -> DayProvider:
    """Config and intent are read per request: the files may change while the service runs."""

    def provide(day: date) -> day_view.DayView:
        s = day_view.day_settings(config.load())
        with open_readonly(settings.dsn) as conn:
            return day_view.load_day_view(conn, settings.athlete_id, day, s)

    return provide


def db_questions_provider(settings: WebSettings) -> QuestionsProvider:
    def provide() -> Sequence[day_view.OpenQuestion]:
        with open_readonly(settings.dsn) as conn:
            return day_view.all_open_questions(conn, settings.athlete_id)

    return provide


def config_today() -> date:
    return datetime.now(ZoneInfo(config.load().timezone)).date()


def pg_store_provider(settings: WebSettings) -> StoreProvider:
    @contextmanager
    def provide() -> Iterator[ClaimsStore]:
        with db.connect(settings.dsn) as conn:
            yield PgStore(conn)

    return provide


def _gate(token: str, tool: str) -> None:
    try:
        require_human(token, tool)
    except HumanTokenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None


def _check_reason(reason: str) -> str:
    if not reason.strip():
        raise HTTPException(status_code=400, detail="a reason is required")
    return reason.strip()


def _back_to(claim_id: str) -> RedirectResponse:
    return RedirectResponse(f"/claims#row-{claim_id}", status_code=303)


def _add_read_routes(
    app: FastAPI, report: ReportProvider, day: DayProvider, today: TodayProvider
) -> None:
    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/claims")

    @app.get("/claims.json")
    def claims_json() -> JSONResponse:
        return JSONResponse(as_json(report()))

    @app.get("/claims", response_class=HTMLResponse)
    def claims(shadows: int = 1) -> HTMLResponse:
        return HTMLResponse(claims_page(report(), shadows=shadows != 0))

    @app.get("/day")
    def day_today() -> RedirectResponse:
        return RedirectResponse(f"/day/{today().isoformat()}")

    # registered before /day/{on}: that pattern would also match "<date>.json"
    @app.get("/day/{on}.json")
    def day_json(on: date) -> JSONResponse:
        return JSONResponse(day_view.as_json(day(on)))

    @app.get("/day/{on}", response_class=HTMLResponse)
    def day_html(on: date) -> HTMLResponse:
        return HTMLResponse(day_page(day(on)))


def _add_client_routes(
    app: FastAPI, settings: WebSettings, questions: QuestionsProvider, store: StoreProvider
) -> None:
    """JSON for clients that read without HTML (the chat layer)."""

    @app.get("/questions.json")
    def questions_json() -> JSONResponse:
        return JSONResponse(day_view.questions_json(settings.athlete_id, questions()))

    @app.get("/claims/{claim_id}/history.json")
    def history(claim_id: str) -> JSONResponse:
        with store() as s:
            rows = s.history(claim_id)
        if not rows:  # every claim has at least its proposal row
            raise HTTPException(status_code=404, detail="no such claim")
        return JSONResponse({"claim_id": claim_id, "history": history_json(rows)})


def _add_gate_routes(app: FastAPI, store: StoreProvider) -> None:
    @app.post("/claims/{claim_id}/decide")
    def decide(
        claim_id: str,
        status: Annotated[str, Form()] = "",
        reason: Annotated[str, Form()] = "",
        token: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        _gate(token, "confirm_or_retire")
        if status not in DECISIONS:
            raise HTTPException(status_code=400, detail="status must be active or retired")
        why = _check_reason(reason)
        try:
            with store() as s:
                s.confirm_or_retire(claim_id, status, why, DECIDED_BY)
        except ClaimNotFoundError:
            raise HTTPException(status_code=404, detail="no such claim") from None
        return _back_to(claim_id)

    @app.post("/claims/{claim_id}/clear-flags")
    def clear_flags(
        claim_id: str,
        reason: Annotated[str, Form()] = "",
        token: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        _gate(token, "clear_flags")
        why = _check_reason(reason)
        try:
            with store() as s:
                s.clear_flags(claim_id, why, DECIDED_BY)
        except ClaimNotFoundError:
            raise HTTPException(status_code=404, detail="no such claim") from None
        return _back_to(claim_id)


def create_app(
    settings: WebSettings,
    report: ReportProvider | None = None,
    day: DayProvider | None = None,
    today: TodayProvider | None = None,
    store: StoreProvider | None = None,
    questions: QuestionsProvider | None = None,
) -> FastAPI:
    uses_db = report is None or day is None or store is None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if uses_db:  # the database is ours: bring its schema up to date once
            with db.connect(settings.dsn) as conn:
                db.migrate(conn)
        yield

    app = FastAPI(title="domestique", docs_url=None, redoc_url=None, lifespan=lifespan)
    _add_read_routes(
        app,
        report or db_provider(settings),
        day or db_day_provider(settings),
        today or config_today,
    )
    claims_store = store or pg_store_provider(settings)
    _add_client_routes(app, settings, questions or db_questions_provider(settings), claims_store)
    _add_gate_routes(app, claims_store)
    return app
