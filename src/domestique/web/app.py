"""The web console's HTTP application.

``create_app`` takes the settings and, for tests, a ``ReportData`` provider;
without one, every request reads the report from the database over a
read-only connection. Routes:

- ``GET /healthz``: ``{"ok": true}``
- ``GET /claims.json``: the report as JSON, every scored prediction
- ``GET /claims``: the claims report page; ``?shadows=0`` hides shadow predictions
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from domestique import db
from domestique.ingest.settings import cli_settings
from domestique.replay.pg import open_readonly
from domestique.web.pages import claims_page
from domestique.web.queries import ReportData, as_json, from_db

type ReportProvider = Callable[[], ReportData]


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


def create_app(settings: WebSettings, report: ReportProvider | None = None) -> FastAPI:
    provide = report or db_provider(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if report is None:  # the database is ours: bring its schema up to date once
            with db.connect(settings.dsn) as conn:
                db.migrate(conn)
        yield

    app = FastAPI(title="domestique", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/claims")

    @app.get("/claims.json")
    def claims_json() -> JSONResponse:
        return JSONResponse(as_json(provide()))

    @app.get("/claims", response_class=HTMLResponse)
    def claims(shadows: int = 1) -> HTMLResponse:
        return HTMLResponse(claims_page(provide(), shadows=shadows != 0))

    return app
