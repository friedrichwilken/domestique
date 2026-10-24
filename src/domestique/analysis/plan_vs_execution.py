"""Plan versus execution: what was prescribed next to what was ridden.

The prescription's heart-rate guidance is read from its description text
("ca. 75% HFmax", "60-75% of max"). That text is often boilerplate, so a gap
between it and the ride is never treated as an execution error: it becomes a
question for the athlete that states both numbers and asks about intent.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from psycopg.types.json import Jsonb

from domestique import db
from domestique.config import DEFAULT_MARGIN_PP
from domestique.ingest.plan_store import ExecutedSession, PlannedSession, PlanStore, WorkInterval

_HR_GUIDANCE = re.compile(
    r"(?P<low>\d{2,3})(?:\s*(?:-|\u2013|to)\s*(?P<high>\d{2,3}))?\s*%\s*"
    r"(?:of\s+)?(?:max(?:imum)?\.?\s*(?:hr|heart\s*rate)?(?!\s*(?:power|watts))|"
    r"(?:hr|hf)\s*max|max\s*hr)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HrGuidance:
    """Prescribed heart rate as percentage of max, as written in the description."""

    low_pct: float
    high_pct: float
    text: str


@dataclass(frozen=True)
class Question:
    athlete_id: str
    text: str
    context: dict[str, object]
    for_: Literal["athlete", "reviewer"] = "athlete"


@dataclass(frozen=True)
class JoinRow:
    planned: PlannedSession
    hr_guidance: HrGuidance | None
    executed: ExecutedSession | None
    work_hr_pct: float | None
    status: Literal["paired", "missed"]
    questions: tuple[Question, ...] = field(default=())


def parse_hr_guidance(description: str | None) -> HrGuidance | None:
    """First heart-rate-of-max figure or range in the text, or None."""
    if not description:
        return None
    m = _HR_GUIDANCE.search(description)
    if m is None:
        return None
    low = float(m["low"])
    high = float(m["high"]) if m["high"] else low
    return HrGuidance(low_pct=min(low, high), high_pct=max(low, high), text=m.group(0))


def work_hr_pct(intervals: Sequence[WorkInterval], hr_max: float) -> float | None:
    """Duration-weighted average heart rate of the work intervals, as percent of hr_max."""
    usable = [(iv.dur_s or 0.0, iv.avg_hr) for iv in intervals if iv.avg_hr is not None]
    total = sum(d for d, _ in usable)
    if not usable or hr_max <= 0:
        return None
    if total > 0:
        mean = sum(d * hr for d, hr in usable) / total
    else:
        mean = sum(hr for _, hr in usable) / len(usable)
    return 100.0 * mean / hr_max


def _fmt(pct: float) -> str:
    return f"{pct:.0f}"


def overshoot_question(
    athlete_id: str,
    planned: PlannedSession,
    guidance: HrGuidance,
    executed_pct: float,
    executed_id: int,
    margin_pp: float = DEFAULT_MARGIN_PP,
) -> Question | None:
    """A question when the work intervals ran above the prescribed HR by more than the margin."""
    if executed_pct <= guidance.high_pct + margin_pp:
        return None
    prescribed = (
        _fmt(guidance.high_pct)
        if guidance.low_pct == guidance.high_pct
        else f"{_fmt(guidance.low_pct)}-{_fmt(guidance.high_pct)}"
    )
    title = planned.title or "the planned session"
    text = (
        f"On {planned.date.isoformat()}, the description of '{title}' gives heart-rate "
        f"guidance of {prescribed}% of max. The work intervals as ridden averaged "
        f"{_fmt(executed_pct)}% of max. Did the session as ridden match what you "
        f"intended for it?"
    )
    context: dict[str, object] = {
        "kind": "plan_vs_execution.hr_overshoot",
        "planned_session_id": planned.id,
        "activity_id": executed_id,
        "date": planned.date.isoformat(),
        "prescribed_hr_pct_low": guidance.low_pct,
        "prescribed_hr_pct_high": guidance.high_pct,
        "prescribed_text": guidance.text,
        "executed_work_hr_pct": round(executed_pct, 1),
        "margin_pp": margin_pp,
    }
    return Question(athlete_id=athlete_id, text=text, context=context)


def _join_one(
    athlete_id: str,
    planned: PlannedSession,
    executed: ExecutedSession | None,
    hr_max: float | None,
    margin_pp: float,
) -> JoinRow:
    guidance = parse_hr_guidance(planned.description)
    pct = work_hr_pct(executed.work_intervals, hr_max) if executed and hr_max else None
    question = None
    if executed is not None and guidance is not None and pct is not None:
        question = overshoot_question(athlete_id, planned, guidance, pct, executed.id, margin_pp)
    return JoinRow(
        planned=planned,
        hr_guidance=guidance,
        executed=executed,
        work_hr_pct=pct,
        status="paired" if executed is not None else "missed",
        questions=(question,) if question else (),
    )


def plan_vs_execution(
    store: PlanStore,
    athlete_id: str,
    day: date,
    hr_max: float | None,
    margin_pp: float = DEFAULT_MARGIN_PP,
) -> list[JoinRow]:
    """One row per planned session on the day, with both the prescription and the execution."""
    rows = []
    for planned in store.planned_on(athlete_id, day):
        aid = planned.paired_activity_id
        executed = store.executed(aid) if aid is not None else None
        rows.append(_join_one(athlete_id, planned, executed, hr_max, margin_pp))
    return rows


def questions_of(rows: Sequence[JoinRow]) -> list[Question]:
    return [q for row in rows for q in row.questions]


def save_questions(conn: db.Conn, questions: Sequence[Question]) -> None:
    """Write questions to the ``questions`` table as open items."""
    for q in questions:
        conn.execute(
            'INSERT INTO questions (athlete_id, "for", text, context) VALUES (%s, %s, %s, %s)',
            (q.athlete_id, q.for_, q.text, Jsonb(q.context)),
        )
