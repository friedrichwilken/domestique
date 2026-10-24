"""The day view: rails, plan versus execution and open questions for one date.

``load_day_view`` reads one ``DayView`` from the database with the existing
loaders and joins (``rails.load.load_day``, ``rails.registry.evaluate``,
``analysis.plan_vs_execution``); ``build_day`` does the same over any plan
store, so the tests need no database. A rail whose action stops the plan or
rules out intensity is listed first and withholds the analysis of the day's
rides: the join is not run and nothing of it is shown. Rail wording and
question text are carried unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from domestique import config, db
from domestique.analysis.plan_vs_execution import JoinRow, plan_vs_execution
from domestique.ingest.plan_store import PgPlanStore, PlanStore
from domestique.intent import load_intent
from domestique.intent.schemas import RailAction
from domestique.rails.load import load_day
from domestique.rails.registry import (
    DEFAULT_LIMITS,
    DayData,
    Limits,
    RailResult,
    evaluate,
    limits_from_intent,
)

# Rails after which no analysis of the day's rides is shown.
WITHHOLDING: frozenset[RailAction] = frozenset({"stop_plan", "no_intensity"})


@dataclass(frozen=True)
class DaySettings:
    """What the day view reads from ``config.yaml`` and ``rails.yaml``."""

    timezone: str = "UTC"
    baselines: Mapping[str, float] = field(default_factory=dict)
    limits: Limits = DEFAULT_LIMITS
    hr_max: float | None = None
    margin_pp: float = config.DEFAULT_MARGIN_PP


def day_settings(cfg: config.Config) -> DaySettings:
    """Timezone, baselines, HRmax and margin from the config; thresholds from the intent rails."""
    return DaySettings(
        timezone=cfg.timezone,
        baselines=cfg.baselines,
        limits=limits_from_intent(load_intent(cfg.intent_dir).rails),
        hr_max=float(cfg.hr_max) if cfg.hr_max else None,
        margin_pp=cfg.overshoot_margin_pp,
    )


@dataclass(frozen=True)
class OpenQuestion:
    id: str
    for_: str
    text: str
    created_at: datetime


@dataclass(frozen=True)
class DayView:
    athlete_id: str
    day: date
    rails: tuple[RailResult, ...]  # withholding rails first
    sessions: tuple[JoinRow, ...]  # empty when a withholding rail fired
    questions: tuple[OpenQuestion, ...]

    @property
    def withheld_by(self) -> tuple[str, ...]:
        """Names of the rails that withhold the analysis of the day's rides."""
        return tuple(r.rail for r in self.rails if r.action in WITHHOLDING)


def order_rails(results: Sequence[RailResult]) -> tuple[RailResult, ...]:
    """Withholding rails first, registry order kept inside each group."""
    return tuple(sorted(results, key=lambda r: r.action not in WITHHOLDING))


def build_day(
    athlete_id: str,
    data: DayData,
    settings: DaySettings,
    plans: PlanStore,
    questions: Sequence[OpenQuestion] = (),
) -> DayView:
    rails = order_rails(evaluate(data, settings.baselines, settings.limits))
    withheld = any(r.action in WITHHOLDING for r in rails)
    sessions = (
        ()
        if withheld
        else tuple(
            plan_vs_execution(plans, athlete_id, data.date, settings.hr_max, settings.margin_pp)
        )
    )
    return DayView(athlete_id, data.date, rails, sessions, tuple(questions))


# A question belongs to the day its context names (plan-vs-execution questions carry
# ``context.date``); one without a date belongs to the day it was asked, in the
# athlete's timezone.
_OPEN_QUESTIONS_SQL = (
    'SELECT id, "for", text, created_at FROM questions '
    "WHERE athlete_id = %s AND status = 'open' "
    "AND COALESCE(context->>'date', ((created_at AT TIME ZONE %s)::date)::text) = %s "
    "ORDER BY created_at, id"
)


def open_questions(
    conn: db.Conn, athlete_id: str, day: date, timezone: str = "UTC"
) -> list[OpenQuestion]:
    rows = conn.execute(_OPEN_QUESTIONS_SQL, (athlete_id, timezone, day.isoformat())).fetchall()
    return [OpenQuestion(str(r[0]), str(r[1]), str(r[2]), r[3]) for r in rows]


_ALL_OPEN_QUESTIONS_SQL = (
    'SELECT id, "for", text, created_at FROM questions '
    "WHERE athlete_id = %s AND status = 'open' ORDER BY created_at, id"
)


def all_open_questions(conn: db.Conn, athlete_id: str) -> list[OpenQuestion]:
    """Every open question for the athlete, oldest first, whatever day it belongs to."""
    rows = conn.execute(_ALL_OPEN_QUESTIONS_SQL, (athlete_id,)).fetchall()
    return [OpenQuestion(str(r[0]), str(r[1]), str(r[2]), r[3]) for r in rows]


def load_day_view(conn: db.Conn, athlete_id: str, day: date, settings: DaySettings) -> DayView:
    data = load_day(conn, athlete_id, day, settings.timezone)
    questions = open_questions(conn, athlete_id, day, settings.timezone)
    return build_day(athlete_id, data, settings, PgPlanStore(conn), questions)


# --- formatting -----------------------------------------------------------------


@dataclass(frozen=True)
class SessionRow:
    """One plan-versus-execution row, every cell already formatted."""

    title: str
    sport: str
    prescribed: str
    status: str
    np: str
    avg_hr: str
    max_hr: str
    intensity: str
    work_hr: str


def _num(value: float | None, unit: str = "") -> str:
    return "-" if value is None else f"{value:.0f}{unit}"


def session_rows(view: DayView) -> list[SessionRow]:
    rows = []
    for r in view.sessions:
        ex = r.executed
        rows.append(
            SessionRow(
                title=r.planned.title or "untitled",
                sport=r.planned.sport or "-",
                prescribed=r.hr_guidance.text if r.hr_guidance else "-",
                status=r.status,
                np=_num(ex.np_w if ex else None, " W"),
                avg_hr=_num(ex.avg_hr if ex else None),
                max_hr=_num(ex.max_hr if ex else None),
                intensity="-"
                if ex is None or ex.intensity_factor is None
                else f"{ex.intensity_factor:.2f}",
                work_hr=_num(r.work_hr_pct, "% of max"),
            )
        )
    return rows


def _iso(value: object) -> object:
    return value.isoformat() if isinstance(value, date) else value


def _session_json(row: JoinRow) -> dict[str, object]:
    return {
        "planned": {k: _iso(v) for k, v in asdict(row.planned).items()},
        "hr_guidance": asdict(row.hr_guidance) if row.hr_guidance else None,
        "executed": (
            {k: _iso(v) for k, v in asdict(row.executed).items()} if row.executed else None
        ),
        "work_hr_pct": row.work_hr_pct,
        "status": row.status,
        "questions": [q.text for q in row.questions],
    }


def question_json(q: OpenQuestion) -> dict[str, object]:
    return {"id": q.id, "for": q.for_, "text": q.text, "created_at": q.created_at.isoformat()}


def as_json(view: DayView) -> dict[str, object]:
    """The day as JSON-ready values; ``plan_vs_execution`` is null when a rail withholds it."""
    withheld = view.withheld_by
    return {
        "athlete_id": view.athlete_id,
        "date": view.day.isoformat(),
        "rails": [asdict(r) for r in view.rails],
        "analysis_withheld_by": list(withheld),
        "plan_vs_execution": None if withheld else [_session_json(r) for r in view.sessions],
        "questions": [question_json(q) for q in view.questions],
    }


def questions_json(athlete_id: str, questions: Sequence[OpenQuestion]) -> dict[str, object]:
    """Open questions as JSON-ready values, text unchanged."""
    return {"athlete_id": athlete_id, "questions": [question_json(q) for q in questions]}
