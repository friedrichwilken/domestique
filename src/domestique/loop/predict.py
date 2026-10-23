"""Rule-based predictions for a planned session. No model call.

``predict`` is a pure function over the planned session, the claims, their
bindings and the history before the session. For each metric:

1. Only claims that are ``active`` and not flagged always-hit are eligible
   (retired, candidate and flagged claims never feed a prediction).
2. Of the eligible claims with a binding for the metric whose conditions match
   the session (intensity, sport, local start hour), the one with the highest
   source layer wins (observed > stated > prior), then the higher confidence.
   The others are recorded in the basis as superseded. No applicable claim:
   no prediction, and a gap names the metric and the reason.
3. The base value comes from the data plane:
   - ``watts_at_hr``: mean power inside the session's target HR band (the
     description's %-of-max guidance times ``hr_max``) over the last
     ``rides`` earlier rides of the same sport family that spent at least
     ``MIN_BAND_SAMPLES`` seconds in the band.
   - ``peak_hr``: the upper bound of that band in bpm (the prescribed
     intensity); the claim's ``offset`` says how far peak runs above it.
   - ``hrv_next_morning`` / ``sleep_hours``: the configured baseline
     (``baselines.hrv`` / ``baselines.sleep_h``), else the median of the last
     ``BASELINE_NIGHTS`` nights when at least ``MIN_BASELINE_NIGHTS`` exist.
4. ``expected = base * (1 + change_pct / 100) + offset`` and the range is
   ``expected -/+ (expected * range_pct / 100 + range_abs)``.

Usage: python -m domestique.loop.predict --date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time
from statistics import median

from domestique import config, db
from domestique.analysis.plan_vs_execution import parse_hr_guidance
from domestique.claims.rules import SourceLayer, Status
from domestique.claims.store import Claim, PgStore
from domestique.ingest.pairing import sport_family
from domestique.ingest.plan_store import PgPlanStore, PlannedSession
from domestique.loop.load import load_history
from domestique.loop.model import (
    BASELINE_NIGHTS,
    Basis,
    Binding,
    Conditions,
    Gap,
    History,
    Metric,
    Prediction,
    PredictionSet,
)
from domestique.loop.store import PgLoopStore
from domestique.metrics import watts_at_hr_band
from domestique.metrics.types import Sample

MIN_BAND_SAMPLES = 300  # ~5 min at 1 Hz inside the band before a ride counts
MIN_BASELINE_NIGHTS = 7
_LAYER_RANK = {SourceLayer.OBSERVED: 0, SourceLayer.STATED: 1, SourceLayer.PRIOR: 2}
_BASELINE_KEY = {Metric.HRV_NEXT_MORNING: "hrv", Metric.SLEEP_HOURS: "sleep_h"}


def eligible(claim: Claim) -> bool:
    """Active and not flagged as always-hit."""
    return claim.status == Status.ACTIVE and not claim.always_hit


def _untimed(session: PlannedSession) -> bool:
    return session.start_local is None or session.start_local.time() == time(0, 0)


def _hour_matches(c: Conditions, session: PlannedSession) -> bool:
    if c.start_hour_from is None or c.start_hour_to is None:
        return True
    if session.start_local is None or _untimed(session):
        return False
    hour = session.start_local.hour
    if c.start_hour_from <= c.start_hour_to:
        return c.start_hour_from <= hour < c.start_hour_to
    return hour >= c.start_hour_from or hour < c.start_hour_to


def _if_matches(c: Conditions, session: PlannedSession) -> bool:
    if c.min_if is None and c.max_if is None:
        return True
    planned = session.planned_if
    if planned is None:
        return False
    return (c.min_if is None or planned >= c.min_if) and (c.max_if is None or planned <= c.max_if)


def applies(c: Conditions, session: PlannedSession) -> bool:
    """Whether the session meets every condition the binding sets."""
    families = {sport_family(s) for s in c.sports}
    sport_ok = not c.sports or sport_family(session.sport) in families
    return sport_ok and _if_matches(c, session) and _hour_matches(c, session)


def _rank(claim: Claim) -> tuple[int, float, str]:
    return (_LAYER_RANK[claim.source_layer], -claim.confidence, claim.id)


def pick(
    metric: Metric,
    session: PlannedSession,
    claims: Mapping[str, Claim],
    bindings: Sequence[Binding],
) -> tuple[Binding, list[str]] | None:
    """The winning binding for the metric and the claim ids it supersedes, or None."""
    usable = [
        b
        for b in bindings
        if b.metric == metric
        and b.claim_id in claims
        and eligible(claims[b.claim_id])
        and applies(b.when, session)
    ]
    if not usable:
        return None
    usable.sort(key=lambda b: _rank(claims[b.claim_id]))
    return usable[0], [b.claim_id for b in usable[1:]]


def target_hr_band(session: PlannedSession, hr_max: float | None) -> tuple[float, float] | str:
    """The prescribed HR band in bpm, or the reason there is none."""
    guidance = parse_hr_guidance(session.description)
    if guidance is None:
        return "no heart-rate guidance in the session description"
    if not hr_max:
        return "hr_max is not configured"
    return (guidance.low_pct * hr_max / 100, guidance.high_pct * hr_max / 100)


def _in_band(samples: Sequence[Sample], low: float, high: float) -> int:
    return sum(
        1 for s in samples if s.get("watts") is not None and low <= (s.get("hr") or 0) <= high
    )


def band_watts(samples: Sequence[Sample], low: float, high: float) -> float | None:
    """Mean watts inside the band, or None with fewer than ``MIN_BAND_SAMPLES`` samples there."""
    if _in_band(samples, low, high) < MIN_BAND_SAMPLES:
        return None
    return watts_at_hr_band(samples, low, high)


type _Base = tuple[float, Basis] | str


def _watts_base(session: PlannedSession, history: History, b: Binding) -> _Base:
    band = target_hr_band(session, history.hr_max)
    if isinstance(band, str):
        return band
    low, high = band
    found: list[tuple[int, float]] = []
    for ride in history.rides:
        watts = band_watts(ride.samples, low, high)
        if watts is not None:
            found.append((ride.activity_id, watts))
        if len(found) == b.rides:
            break
    if len(found) < b.rides:
        return (
            f"only {len(found)} of {b.rides} earlier rides spent "
            f"{MIN_BAND_SAMPLES} s in the {low:.0f}-{high:.0f} bpm band"
        )
    base = sum(w for _, w in found) / len(found)
    basis: Basis = {
        "hr_low": round(low, 1),
        "hr_high": round(high, 1),
        "rides": [aid for aid, _ in found],
    }
    return base, basis


def _peak_base(session: PlannedSession, history: History) -> _Base:
    band = target_hr_band(session, history.hr_max)
    if isinstance(band, str):
        return band
    return band[1], {"hr_low": round(band[0], 1), "hr_high": round(band[1], 1)}


def _baseline(metric: Metric, history: History) -> _Base:
    key = _BASELINE_KEY[metric]
    if key in history.baselines:
        return history.baselines[key], {"baseline_from": "config"}
    nights = history.hrv if metric == Metric.HRV_NEXT_MORNING else history.sleep_h
    recent = nights[:BASELINE_NIGHTS]
    if len(recent) < MIN_BASELINE_NIGHTS:
        return (
            f"no baseline: set baselines.{key} or ingest at least "
            f"{MIN_BASELINE_NIGHTS} nights of wellness"
        )
    return median(recent), {"baseline_from": f"median of last {len(recent)} nights"}


def base_value(
    metric: Metric, session: PlannedSession, history: History, binding: Binding
) -> _Base:
    """The data-plane base for the metric with how it was found, or the gap reason."""
    if metric == Metric.WATTS_AT_HR:
        return _watts_base(session, history, binding)
    if metric == Metric.PEAK_HR:
        return _peak_base(session, history)
    return _baseline(metric, history)


@dataclass(frozen=True)
class Shaped:
    expected: float
    low: float
    high: float


def shape(base: float, b: Binding) -> Shaped:
    """Apply the binding's documented rule to the base value."""
    expected = base * (1 + b.change_pct / 100) + b.offset
    half = abs(expected) * b.range_pct / 100 + b.range_abs
    return Shaped(round(expected, 2), round(expected - half, 2), round(expected + half, 2))


def _predict_metric(
    metric: Metric,
    session: PlannedSession,
    claims: Mapping[str, Claim],
    bindings: Sequence[Binding],
    history: History,
) -> Prediction | Gap:
    chosen = pick(metric, session, claims, bindings)
    if chosen is None:
        return Gap(session.id, metric, f"no active claim with a binding for {metric} applies")
    binding, superseded = chosen
    found = base_value(metric, session, history, binding)
    if isinstance(found, str):
        return Gap(session.id, metric, found)
    base, basis = found
    s = shape(base, binding)
    basis = {**basis, "base": round(base, 2)}
    if superseded:
        basis["superseded"] = superseded
    return Prediction(session.id, metric, s.expected, s.low, s.high, (binding.claim_id,), basis)


def predict(
    session: PlannedSession,
    claims: Sequence[Claim],
    bindings: Sequence[Binding],
    history: History,
) -> PredictionSet:
    """Predictions for every metric an applicable active claim informs; gaps for the rest."""
    by_id = {c.id: c for c in claims}
    predictions: list[Prediction] = []
    gaps: list[Gap] = []
    for metric in Metric:
        result = _predict_metric(metric, session, by_id, bindings, history)
        if isinstance(result, Prediction):
            predictions.append(result)
        else:
            gaps.append(result)
    return PredictionSet(tuple(predictions), tuple(gaps))


# --- CLI ----------------------------------------------------------------------


def describe(result: PredictionSet, saved: Sequence[Prediction]) -> str:
    kept = {p.id for p in saved}
    lines = []
    for p in result.predictions:
        state = "recorded" if p.id in kept else "already recorded, first registration kept"
        lines.append(
            f"session {p.planned_session_id} {p.metric}: {p.expected} [{p.low}, {p.high}] "
            f"from claim(s) {', '.join(p.claim_ids)} ({state})"
        )
    lines.extend(
        f"session {g.planned_session_id} {g.metric}: no prediction, {g.reason}" for g in result.gaps
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Record predictions for planned sessions on a day.")
    p.add_argument("--date", required=True, type=date.fromisoformat)
    args = p.parse_args(argv)
    cfg = config.load()
    with db.connect(cfg.database_url) as conn:
        db.migrate(conn)
        loop = PgLoopStore(conn)
        claims = PgStore(conn).query_claims(athlete_id=cfg.athlete_id, status="active")
        bindings = loop.bindings(cfg.athlete_id)
        for session in PgPlanStore(conn).planned_on(cfg.athlete_id, args.date):
            history = load_history(conn, cfg.athlete_id, session, cfg.hr_max, cfg.baselines)
            result = predict(session, claims, bindings, history)
            saved = loop.save_predictions(result.predictions)
            sys.stdout.write(describe(result, saved) + "\n")
        conn.commit()


if __name__ == "__main__":
    main()
