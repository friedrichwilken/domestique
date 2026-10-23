"""The replay: walk a season day by day through a cursor view, predict, then score.

For each day D of the season, with the cursor at D:

1. Score the sessions planned on D-1. Their ride is now visible, and so is the
   morning reading of D (sleep and HRV after the session). Scoring is
   ``loop.score.score`` and ``loop.score.apply``, the same code as the nightly
   run; with the loop off, outcomes are written but no claim's confidence moves.
2. Predict the sessions planned on D with ``loop.predict.predict``, from the
   history the view allows: earlier rides of the session's sport family and
   the recent nights.

After the last day the cursor moves one more day so the last sessions are
scored. Claims and predictions live in in-memory stores seeded from a priors
file; nothing is written to the athlete's claims store. Configured baselines
are not used: they are set today, after the replayed range, and would leak.
"""

from __future__ import annotations

import itertools
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from domestique.analysis.plan_vs_execution import (
    Question,
    overshoot_question,
    parse_hr_guidance,
    work_hr_pct,
)
from domestique.claims.seed import Seed, load_seed
from domestique.claims.store import Claim, EvidenceInput, MemoryStore
from domestique.ingest.pairing import sport_family
from domestique.ingest.plan_store import PlannedSession
from domestique.loop.load import LOOKBACK_DAYS, MAX_RIDES
from domestique.loop.model import (
    BASELINE_NIGHTS,
    Actuals,
    Binding,
    History,
    Metric,
    Outcome,
    Prediction,
    RideSamples,
)
from domestique.loop.predict import predict
from domestique.loop.score import apply, score
from domestique.loop.store import MemoryLoopStore
from domestique.replay.source import CursorView, SeasonSource

REPLAY_BY = "replay"
EVENING_FROM = 17  # local hour, the planted effect's definition of evening
EVENING_TO = 23
HARD_IF = 0.85  # planned intensity factor from which a session counts as intensity


def evening_intensity(session: PlannedSession) -> bool:
    """Planned IF of at least ``HARD_IF`` and a local start in ``[EVENING_FROM, EVENING_TO)``."""
    if session.planned_if is None or session.start_local is None:
        return False
    hour = session.start_local.hour
    return session.planned_if >= HARD_IF and EVENING_FROM <= hour < EVENING_TO


@dataclass(frozen=True)
class Scored:
    """One scored prediction, with the session it was for and where the actual came from."""

    session: PlannedSession
    prediction: Prediction
    outcome: Outcome
    evidence: EvidenceInput

    @property
    def hit(self) -> bool:
        return self.prediction.hit(self.outcome.actual)


@dataclass
class RunResult:
    athlete_id: str
    first: date
    last: date
    loop_on: bool
    seeded: dict[str, tuple[Binding, ...]] = field(default_factory=dict)  # claim id -> bindings
    scored: list[Scored] = field(default_factory=list)
    gaps: Counter[tuple[Metric, str]] = field(default_factory=Counter)
    pending: Counter[tuple[Metric, str]] = field(default_factory=Counter)
    predictions: int = 0
    sessions: int = 0
    questions: list[Question] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)  # final state of the working store


def history_for(view: CursorView, session: PlannedSession) -> History:
    """What ``loop.load.load_history`` reads from the database, read through the view."""
    family = sport_family(session.sport)
    before = session.date - timedelta(days=1)
    rides = [
        r
        for r in view.rides(session.date - timedelta(days=LOOKBACK_DAYS), before)
        if family is None or sport_family(r.sport) == family
    ][:MAX_RIDES]
    nights = view.nights(session.date - timedelta(days=BASELINE_NIGHTS - 1), session.date)
    return History(
        hr_max=view.hr_max,
        rides=tuple(RideSamples(r.id, view.samples(r.id)) for r in rides),
        hrv=tuple(n.hrv for n in nights if n.hrv is not None),
        sleep_h=tuple(n.sleep_h for n in nights if n.sleep_h is not None),
    )


def actuals_for(view: CursorView, session: PlannedSession) -> Actuals:
    """What ``loop.load.load_actuals`` reads, through the view: the ride and the next morning."""
    morning = view.night(session.date + timedelta(days=1))
    hrv = None if morning is None else morning.hrv
    sleep = None if morning is None else morning.sleep_h
    aid = session.paired_activity_id
    ride = None if aid is None else view.ride(aid)
    if ride is None:
        return Actuals(None, hrv_next_morning=hrv, sleep_hours=sleep)
    return Actuals(
        activity_id=ride.id,
        samples=view.samples(ride.id),
        max_hr=ride.max_hr,
        hrv_next_morning=hrv,
        sleep_hours=sleep,
    )


def overshoot_for(view: CursorView, session: PlannedSession) -> Question | None:
    """The plan-vs-execution heart-rate overshoot question, computed through the view."""
    guidance = parse_hr_guidance(session.description)
    aid = session.paired_activity_id
    ride = None if aid is None else view.ride(aid)
    if guidance is None or ride is None or not view.hr_max:
        return None
    pct = work_hr_pct(ride.work_intervals, view.hr_max)
    if pct is None:
        return None
    return overshoot_question(view.athlete_id, session, guidance, pct, ride.id)


def evidence_for(p: Prediction, session: PlannedSession, actuals: Actuals) -> EvidenceInput:
    if p.metric in (Metric.HRV_NEXT_MORNING, Metric.SLEEP_HOURS):
        morning = session.date + timedelta(days=1)
        return {"kind": "wellness", "ref": f"wellness/{morning.isoformat()}", "note": p.metric}
    return {"kind": "activity", "ref": f"activity/{actuals.activity_id}", "note": p.metric}


class Replay:
    """One replay run. ``loop_on=False`` scores but never moves a claim's confidence."""

    def __init__(self, source: SeasonSource, priors: Seed, loop_on: bool = True) -> None:
        self._source = source
        counter = itertools.count(1)
        self.claims = MemoryStore(new_id=lambda: str(uuid.UUID(int=next(counter))))
        self.loop = MemoryLoopStore()
        self.result = RunResult(source.athlete_id, source.first, source.last, loop_on)
        loaded = load_seed(
            priors, self.claims, self.loop, source.athlete_id, activate=True, by=REPLAY_BY
        )
        self.result.seeded = {c.id: bound for c, bound in loaded}

    def predict_day(self, view: CursorView) -> None:
        who = self.result.athlete_id
        for session in view.planned_on(view.cursor):
            self.result.sessions += 1
            active = self.claims.query_claims(athlete_id=who, status="active")
            out = predict(session, active, self.loop.bindings(who), history_for(view, session))
            self.result.predictions += len(self.loop.save_predictions(out.predictions))
            self.result.gaps.update((g.metric, g.reason) for g in out.gaps)

    def score_day(self, view: CursorView, day: date) -> None:
        who = self.result.athlete_id
        for session in view.planned_on(day):
            actuals = actuals_for(view, session)
            predictions = self.loop.predictions_for(session.id)
            result = score(
                who,
                session,
                predictions,
                self.loop.scored_ids(session.id),
                actuals,
                self.claims.query_claims(athlete_id=who),
                overshoot_for(view, session),
            )
            if not self.result.loop_on:
                result = replace(result, adjustments=())
            apply(result, self.loop, self.claims, by=REPLAY_BY)
            self.result.pending.update((p.metric, p.reason) for p in result.pending)
            by_id = {p.id: p for p in predictions}
            self.result.scored.extend(
                Scored(
                    session,
                    by_id[o.prediction_id],
                    o,
                    evidence_for(by_id[o.prediction_id], session, actuals),
                )
                for o in result.outcomes
            )

    def run(self) -> RunResult:
        day = self.result.first
        while day <= self.result.last + timedelta(days=1):
            view = CursorView(self._source, day)
            self.score_day(view, day - timedelta(days=1))
            if day <= self.result.last:
                self.predict_day(view)
            day += timedelta(days=1)
        self.result.questions = list(self.loop.questions)
        self.result.claims = self.claims.query_claims()
        return self.result


def run_replay(source: SeasonSource, priors: Seed, loop_on: bool = True) -> RunResult:
    return Replay(source, priors, loop_on).run()


def scored_for(result: RunResult, metric: Metric) -> Sequence[Scored]:
    return [s for s in result.scored if s.prediction.metric == metric]
