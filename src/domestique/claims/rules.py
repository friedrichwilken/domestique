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
- Always-hit flag: a claim with at least ``FLAG_MIN_SCORED`` (10) scored
  predictions and a hit rate above ``FLAG_HIT_RATE`` (95%), counted before the
  prediction being scored, has ranges too wide to mean anything. It is
  flagged (``always_hit``, plus a history note), and while flagged a hit no
  longer raises its confidence. Misses still lower it. The flag stays until
  a human clears it (``ClaimsStore.clear_always_hit``).
- Every scored prediction increments ``scored`` and, on a hit, ``hits``.
- Retired claims are never adjusted (they are no longer tested).

``adjust_confidence`` returns the updated claim; ``adjust_with_notes`` also
returns the history notes (refused promotion, flag set) for the caller to
persist with ``record_adjustment``.
"""

from __future__ import annotations

from dataclasses import replace
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
FLAG_MIN_SCORED = 10
FLAG_HIT_RATE = 0.95


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


def adjust_confidence(claim: Claim, hit: bool) -> Claim:
    """Return an updated copy of ``claim`` after a scored prediction."""
    return adjust_with_notes(claim, hit)[0]


def _always_hit_check(claim: Claim) -> tuple[bool, list[str]]:
    """Whether the always-hit flag is (now) set, plus the note if it was just raised."""
    if claim.always_hit:
        return True, []
    if claim.scored >= FLAG_MIN_SCORED and claim.hits / claim.scored > FLAG_HIT_RATE:
        note = (
            f"always-hit flag set: {claim.hits}/{claim.scored} scored predictions hit, "
            "ranges are uninformative; hits no longer raise confidence"
        )
        return True, [note]
    return False, []


def _apply_outcome(claim: Claim, hit: bool, flagged: bool) -> tuple[float, int]:
    """Raw confidence and hit streak after one outcome, before caps and promotion."""
    if hit:
        confidence = claim.confidence if flagged else min(CONF_MAX, claim.confidence + HIT_STEP)
        return confidence, claim.hit_streak + 1
    return max(CONF_MIN, claim.confidence - MISS_STEP), 0


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


def adjust_with_notes(claim: Claim, hit: bool) -> tuple[Claim, list[str]]:
    """Return ``(updated claim, history notes)`` after a scored prediction.

    Works on any dataclass with source_layer, horizon, confidence, status,
    hit_streak, scored, hits and always_hit.
    """
    if claim.status == Status.RETIRED:
        return claim, []
    flagged, notes = _always_hit_check(claim)
    confidence, streak = _apply_outcome(claim, hit, flagged)
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
        always_hit=flagged,
    )
    return updated, notes
