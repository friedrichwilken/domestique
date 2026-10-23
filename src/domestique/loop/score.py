"""Nightly scoring: fill outcomes for a session's predictions and move confidence.

``score`` is a pure function; ``apply`` writes its result through the stores.
For each prediction of the session that has no outcome yet:

1. The actual comes from the data plane: mean watts inside the prediction's
   pre-registered HR band (``basis.hr_low``/``hr_high``) over the paired ride,
   the ride's max HR, and HRV and sleep from the morning after. A value that
   does not exist yet (session not ridden, too little time in the band, no
   wellness for the next morning) leaves the prediction pending, unscored.
2. The outcome records the actual and the signed error ``actual - expected``.
   It is a hit when ``low <= actual <= high``.
3. Each cited claim moves by ``claims.rules.adjust_with_notes`` (hit +0.10,
   miss -0.15, layer and horizon caps, promotion, retirement, always-hit flag;
   the rule is documented there), applied in metric order so two predictions
   citing one claim compound. The history row's reason names the prediction.
4. Overshoot: when plan-vs-execution flagged the session as ridden above its
   heart-rate guidance, the session as ridden is not the one predicted, so no
   claim is adjusted, hit or miss. If any prediction missed, one question for
   the athlete lists the misses next to the overshoot, so intent can be told
   apart from physiology.

Scored once: the store writes an outcome only if none exists, and adjustments
and questions are applied only for outcomes this run wrote.

Usage: python -m domestique.loop.score --date YYYY-MM-DD  (the session day; run
it once the next morning's wellness is in)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from domestique import config, db
from domestique.analysis.plan_vs_execution import JoinRow, Question, plan_vs_execution
from domestique.claims.rules import Status, adjust_with_notes
from domestique.claims.store import Claim, ClaimsStore, PgStore
from domestique.ingest.plan_store import PgPlanStore, PlannedSession
from domestique.loop.load import load_actuals
from domestique.loop.model import Actuals, Metric, Outcome, Prediction
from domestique.loop.predict import MIN_BAND_SAMPLES, band_watts
from domestique.loop.store import LoopStore, PgLoopStore

OVERSHOOT_KIND = "plan_vs_execution.hr_overshoot"
QUESTION_KIND = "prediction_loop.overshoot_miss"
SCORER = "loop:score"

_LABEL = {
    Metric.WATTS_AT_HR: "watts at target heart rate",
    Metric.PEAK_HR: "peak heart rate",
    Metric.HRV_NEXT_MORNING: "next-morning HRV",
    Metric.SLEEP_HOURS: "sleep hours",
}


@dataclass(frozen=True)
class Pending:
    prediction_id: str
    metric: Metric
    reason: str


@dataclass(frozen=True)
class Adjustment:
    prediction_id: str
    claim: Claim  # the claim as it should be stored after this outcome
    reason: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class DraftQuestion:
    question: Question
    prediction_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScoreResult:
    outcomes: tuple[Outcome, ...]
    adjustments: tuple[Adjustment, ...]
    questions: tuple[DraftQuestion, ...]
    pending: tuple[Pending, ...]


def _basis_float(p: Prediction, key: str) -> float | None:
    value = p.basis.get(key)
    return float(value) if isinstance(value, int | float) else None


def _watts_actual(p: Prediction, actuals: Actuals) -> float | str:
    low, high = _basis_float(p, "hr_low"), _basis_float(p, "hr_high")
    if low is None or high is None:
        return "prediction has no recorded heart-rate band"
    watts = band_watts(actuals.samples, low, high)
    if watts is None:
        return f"ride spent under {MIN_BAND_SAMPLES} s in the {low:.0f}-{high:.0f} bpm band"
    return watts


def actual_for(p: Prediction, actuals: Actuals) -> float | str:
    """The measured value for the prediction's metric, or why it does not exist yet."""
    if actuals.activity_id is None:
        return "session was not ridden"
    if p.metric == Metric.WATTS_AT_HR:
        return _watts_actual(p, actuals)
    values = {
        Metric.PEAK_HR: actuals.max_hr,
        Metric.HRV_NEXT_MORNING: actuals.hrv_next_morning,
        Metric.SLEEP_HOURS: actuals.sleep_hours,
    }
    value = values[p.metric]
    return f"no {_LABEL[p.metric]} recorded yet" if value is None else value


def _verdict(p: Prediction, o: Outcome) -> str:
    word = "hit" if p.hit(o.actual) else "miss"
    return (
        f"prediction {p.id} ({p.metric}): {word}, actual {o.actual:g} "
        f"against {p.expected:g} [{p.low:g}, {p.high:g}]"
    )


def _adjust(p: Prediction, o: Outcome, current: dict[str, Claim]) -> list[Adjustment]:
    """Apply the confidence rule to each cited claim, carrying state for later predictions."""
    out = []
    for cid in p.claim_ids:
        claim = current.get(cid)
        if claim is None or claim.status == Status.RETIRED:
            continue
        updated, notes = adjust_with_notes(claim, p.hit(o.actual))
        current[cid] = updated
        out.append(Adjustment(p.id, updated, _verdict(p, o), tuple(notes)))
    return out


def _miss_line(p: Prediction, o: Outcome) -> str:
    return (
        f"{_LABEL[p.metric]} was predicted at {p.expected:g} ({p.low:g}-{p.high:g}) "
        f"and came in at {o.actual:g}"
    )


def overshoot_question(
    athlete_id: str,
    session: PlannedSession,
    overshoot: Question,
    misses: Sequence[tuple[Prediction, Outcome]],
) -> DraftQuestion:
    """One question for the athlete: the overshoot next to the predictions it made miss."""
    title = session.title or "the planned session"
    executed = overshoot.context.get("executed_work_hr_pct")
    text = (
        f"On {session.date.isoformat()}, '{title}' was ridden above its heart-rate guidance "
        f"(work intervals at {executed}% of max). "
        + "; ".join(_miss_line(p, o) for p, o in misses)
        + ". These misses were not counted against what the system has learned about you, "
        "because the session as ridden was not the one predicted. Was the harder riding "
        "what you intended for this session?"
    )
    context: dict[str, object] = {
        "kind": QUESTION_KIND,
        "planned_session_id": session.id,
        "date": session.date.isoformat(),
        "overshoot": dict(overshoot.context),
        "misses": [
            {
                "prediction_id": p.id,
                "metric": p.metric.value,
                "expected": p.expected,
                "low": p.low,
                "high": p.high,
                "actual": o.actual,
                "error": o.error,
                "claim_ids": list(p.claim_ids),
            }
            for p, o in misses
        ],
    }
    return DraftQuestion(
        Question(athlete_id=athlete_id, text=text, context=context),
        tuple(p.id for p, _ in misses),
    )


def overshoot_flag(rows: Sequence[JoinRow], planned_session_id: int) -> Question | None:
    """The plan-vs-execution overshoot question for the session, if it was flagged."""
    for row in rows:
        if row.planned.id != planned_session_id:
            continue
        for q in row.questions:
            if q.context.get("kind") == OVERSHOOT_KIND:
                return q
    return None


def _measure(
    todo: Sequence[Prediction], actuals: Actuals
) -> tuple[list[tuple[Prediction, Outcome]], list[Pending]]:
    scored: list[tuple[Prediction, Outcome]] = []
    pending: list[Pending] = []
    for p in todo:
        actual = actual_for(p, actuals)
        if isinstance(actual, str):
            pending.append(Pending(p.id, p.metric, actual))
            continue
        actual = round(actual, 3)
        scored.append((p, Outcome(p.id, actual, round(actual - p.expected, 3))))
    return scored, pending


def score(
    athlete_id: str,
    session: PlannedSession,
    predictions: Sequence[Prediction],
    scored_ids: set[str],
    actuals: Actuals,
    claims: Sequence[Claim],
    overshoot: Question | None,
) -> ScoreResult:
    """Score the session's unscored predictions; see the module docstring for the rule."""
    todo = sorted((p for p in predictions if p.id not in scored_ids), key=lambda p: p.metric)
    scored, pending = _measure(todo, actuals)
    adjustments: list[Adjustment] = []
    questions: list[DraftQuestion] = []
    if overshoot is None:
        current = {c.id: c for c in claims}
        for p, o in scored:
            adjustments.extend(_adjust(p, o, current))
    else:
        misses = [(p, o) for p, o in scored if not p.hit(o.actual)]
        if misses:
            questions.append(overshoot_question(athlete_id, session, overshoot, misses))
    return ScoreResult(
        outcomes=tuple(o for _, o in scored),
        adjustments=tuple(adjustments),
        questions=tuple(questions),
        pending=tuple(pending),
    )


@dataclass(frozen=True)
class Applied:
    outcomes: int
    adjustments: int
    questions: int


def apply(result: ScoreResult, loop: LoopStore, claims: ClaimsStore, by: str = SCORER) -> Applied:
    """Write outcomes once; adjust claims and save questions only for outcomes written now."""
    written = {o.prediction_id for o in result.outcomes if loop.record_outcome(o)}
    adjusted = 0
    for a in result.adjustments:
        if a.prediction_id in written:
            claims.record_adjustment(a.claim, a.reason, by, a.notes)
            adjusted += 1
    asked = 0
    for d in result.questions:
        if written.intersection(d.prediction_ids):
            loop.save_question(d.question)
            asked += 1
    return Applied(len(written), adjusted, asked)


def score_session(
    athlete_id: str,
    session: PlannedSession,
    loop: LoopStore,
    claims: ClaimsStore,
    actuals: Actuals,
    overshoot: Question | None,
) -> tuple[ScoreResult, Applied]:
    """Read the session's predictions and claims from the stores, score, and apply."""
    result = score(
        athlete_id,
        session,
        loop.predictions_for(session.id),
        loop.scored_ids(session.id),
        actuals,
        claims.query_claims(athlete_id=athlete_id),
        overshoot,
    )
    return result, apply(result, loop, claims)


# --- CLI ----------------------------------------------------------------------


def describe(session_id: int, result: ScoreResult, applied: Applied) -> str:
    lines = [
        f"session {session_id}: {applied.outcomes} outcome(s), "
        f"{applied.adjustments} claim adjustment(s), {applied.questions} question(s)"
    ]
    lines.extend(
        f"  {a.reason}: claim {a.claim.id} now {a.claim.confidence}" for a in result.adjustments
    )
    lines.extend(f"  pending {p.metric}: {p.reason}" for p in result.pending)
    return "\n".join(lines)


def _sessions(rows: Sequence[JoinRow]) -> Mapping[int, PlannedSession]:
    return {row.planned.id: row.planned for row in rows}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Score predictions for planned sessions on a day.")
    p.add_argument("--date", required=True, type=date.fromisoformat)
    args = p.parse_args(argv)
    cfg = config.load()
    with db.connect(cfg.database_url) as conn:
        db.migrate(conn)
        loop, claims = PgLoopStore(conn), PgStore(conn)
        rows = plan_vs_execution(PgPlanStore(conn), cfg.athlete_id, args.date, cfg.hr_max)
        for sid, session in _sessions(rows).items():
            actuals = load_actuals(conn, cfg.athlete_id, session)
            flag = overshoot_flag(rows, sid)
            result, applied = score_session(cfg.athlete_id, session, loop, claims, actuals, flag)
            sys.stdout.write(describe(sid, result, applied) + "\n")
        conn.commit()


if __name__ == "__main__":
    main()
