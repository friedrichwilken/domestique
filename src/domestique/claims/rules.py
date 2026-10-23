"""Confidence rules for claims. Pure functions, no I/O.

Rule applied by ``adjust_confidence`` after a prediction that cited a claim
is scored:

- hit:  confidence += 0.10, capped at 0.95; the hit streak grows by one.
- miss: confidence -= 0.15, floored at 0.05; the hit streak resets to zero.
- A ``prior`` with ``PROMOTE_AFTER`` (5) consecutive hits becomes
  ``observed`` (it has now been confirmed on this athlete).
- A claim whose confidence falls under ``RETIRE_BELOW`` (0.1) is retired.
  The floor of 0.05 is below that line, so repeated misses always retire.
- Only ``observed`` claims may exceed ``PRIOR_CAP`` (0.7): priors and
  stated claims are clamped there (DESIGN.md: only observed reaches high
  confidence).
- Horizon caps (DESIGN.md, feedback horizons): on top of the layer cap,
  ``week`` claims are clamped at ``WEEK_CAP`` (0.7) and ``season`` claims at
  ``SEASON_CAP`` (0.5). ``day`` claims have no extra cap.
- A ``season`` prior is never promoted, however many hits it records: one to
  three confounded samples a year cannot be learned from one athlete. The
  refused promotion is returned as a note, which the store writes as its own
  history row (once, when the streak first reaches ``PROMOTE_AFTER``).
- Calibration flags. Each scored prediction adds to the claim's calibration
  window: ``calib_scored``, ``calib_hits``, the sum of absolute errors
  (``calib_abs_error``) and the sum of half-ranges (``calib_half_range``),
  this outcome included. With at least ``CALIB_MIN_SCORED`` (10) in the
  window:

  - *uninformative*: mean absolute error below ``UNINFORMATIVE_RATIO`` (a
    third) of the mean half-range. The range could be three times narrower
    and still hit. Flagged (plus a history note); while flagged a hit no
    longer raises confidence, misses still lower it.
  - *overconfident*: hit rate below ``OVERCONFIDENT_HIT_RATE`` (60%), the
    break-even rate of the hit and miss steps. Flagged (plus a history note),
    and every outcome scored while the window's hit rate is below that line
    costs one extra ``MISS_STEP`` on top of the normal rule.

  Hit rate alone never flags a claim as uninformative: a well-sized range
  hits 85-90% of the time. Both flags stay until a human clears them
  (``ClaimsStore.clear_flags``), which also starts a new calibration window,
  since the old one measured the range before it was changed.
- Every scored prediction increments ``scored`` and, on a hit, ``hits``.
- Retired claims are never adjusted (they are no longer tested).

``adjust_confidence`` returns the updated claim; ``adjust_with_notes`` also
returns the history notes (refused promotion, flags set) for the caller to
persist with ``record_adjustment``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # store imports this module at runtime; importing Claim back would be a cycle.
    from domestique.claims.store import Claim

HIT_STEP = 0.10
MISS_STEP = 0.15
CONF_MAX = 0.95
CONF_MIN = 0.05
PROMOTE_AFTER = 5
RETIRE_BELOW = 0.1
PRIOR_CAP = 0.7
WEEK_CAP = 0.7
SEASON_CAP = 0.5
CALIB_MIN_SCORED = 10
UNINFORMATIVE_RATIO = 1 / 3
OVERCONFIDENT_HIT_RATE = 0.6


class SourceLayer(StrEnum):
    OBSERVED = "observed"
    STATED = "stated"
    PRIOR = "prior"


class Horizon(StrEnum):
    DAY = "day"
    WEEK = "week"
    SEASON = "season"


HORIZON_CAP = {Horizon.DAY: CONF_MAX, Horizon.WEEK: WEEK_CAP, Horizon.SEASON: SEASON_CAP}


class Status(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    CANDIDATE = "candidate"


@dataclass(frozen=True)
class Calibration:
    """A claim's calibration window after one more outcome, and the flags it raises."""

    scored: int
    hits: int
    abs_error: float
    half_range: float

    @property
    def ready(self) -> bool:
        return self.scored >= CALIB_MIN_SCORED

    @property
    def uninformative(self) -> bool:
        return self.ready and self.abs_error < UNINFORMATIVE_RATIO * self.half_range

    @property
    def overconfident(self) -> bool:
        return self.ready and self.hits / self.scored < OVERCONFIDENT_HIT_RATE


def calibration(claim: Claim, hit: bool, abs_error: float, half_range: float) -> Calibration:
    """The claim's window with this outcome added."""
    return Calibration(
        scored=claim.calib_scored + 1,
        hits=claim.calib_hits + (1 if hit else 0),
        abs_error=round(claim.calib_abs_error + abs(abs_error), 6),
        half_range=round(claim.calib_half_range + abs(half_range), 6),
    )


def adjust_confidence(
    claim: Claim, hit: bool, abs_error: float = 0.0, half_range: float = 0.0
) -> Claim:
    """Return an updated copy of ``claim`` after a scored prediction."""
    return adjust_with_notes(claim, hit, abs_error, half_range)[0]


def _flag_notes(claim: Claim, window: Calibration) -> list[str]:
    """History notes for flags this outcome raises for the first time."""
    notes = []
    if window.uninformative and not claim.uninformative:
        notes.append(
            f"uninformative flag set: mean absolute error {window.abs_error / window.scored:.3g} "
            f"is under a third of the mean half-range {window.half_range / window.scored:.3g} "
            f"over {window.scored} scored predictions; hits no longer raise confidence"
        )
    if window.overconfident and not claim.overconfident:
        notes.append(
            f"overconfident flag set: {window.hits}/{window.scored} scored predictions hit, "
            f"under {OVERCONFIDENT_HIT_RATE:.0%}; the range is too narrow, "
            "each outcome costs an extra miss step"
        )
    return notes


def _apply_outcome(
    claim: Claim, hit: bool, uninformative: bool, penalty: bool
) -> tuple[float, int]:
    """Raw confidence and hit streak after one outcome, before caps and promotion."""
    confidence = claim.confidence
    if hit and not uninformative:
        confidence = min(CONF_MAX, confidence + HIT_STEP)
    elif not hit:
        confidence -= MISS_STEP
    if penalty:
        confidence -= MISS_STEP
    return max(CONF_MIN, confidence), (claim.hit_streak + 1 if hit else 0)


def _promote(layer: SourceLayer, horizon: Horizon, streak: int) -> tuple[SourceLayer, list[str]]:
    """Promote a prior after enough consecutive hits; season priors are refused (noted once)."""
    if layer != SourceLayer.PRIOR or streak < PROMOTE_AFTER:
        return layer, []
    if horizon != Horizon.SEASON:
        return SourceLayer.OBSERVED, []
    if streak == PROMOTE_AFTER:
        return layer, [f"promotion refused: season-horizon claim stays prior after {streak} hits"]
    return layer, []


def _capped(confidence: float, layer: SourceLayer, horizon: Horizon) -> float:
    """Apply the layer cap (non-observed) and the horizon cap, rounded to 3 places."""
    if layer != SourceLayer.OBSERVED:
        confidence = min(confidence, PRIOR_CAP)
    return round(min(confidence, HORIZON_CAP[horizon]), 3)


def adjust_with_notes(
    claim: Claim, hit: bool, abs_error: float = 0.0, half_range: float = 0.0
) -> tuple[Claim, list[str]]:
    """Return ``(updated claim, history notes)`` after a scored prediction.

    ``abs_error`` is ``|actual - expected|`` and ``half_range`` is
    ``(high - low) / 2`` of the scored prediction, in the metric's unit.
    Works on any dataclass with the fields of ``claims.store.Claim``.
    """
    if claim.status == Status.RETIRED:
        return claim, []
    window = calibration(claim, hit, abs_error, half_range)
    notes = _flag_notes(claim, window)
    uninformative = claim.uninformative or window.uninformative
    confidence, streak = _apply_outcome(claim, hit, uninformative, window.overconfident)
    horizon = Horizon(claim.horizon)
    layer, promotion_notes = _promote(claim.source_layer, horizon, streak)
    notes.extend(promotion_notes)
    confidence = _capped(confidence, layer, horizon)
    status = Status.RETIRED if confidence < RETIRE_BELOW else claim.status
    updated = replace(
        claim,
        confidence=confidence,
        hit_streak=streak,
        source_layer=layer,
        status=status,
        scored=claim.scored + 1,
        hits=claim.hits + (1 if hit else 0),
        uninformative=uninformative,
        overconfident=claim.overconfident or window.overconfident,
        calib_scored=window.scored,
        calib_hits=window.hits,
        calib_abs_error=window.abs_error,
        calib_half_range=window.half_range,
    )
    return updated, notes
