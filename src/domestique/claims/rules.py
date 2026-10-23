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


def adjust_confidence(claim, hit: bool):
    """Return an updated copy of ``claim`` after a scored prediction."""
    return adjust_with_notes(claim, hit)[0]


def adjust_with_notes(claim, hit: bool):
    """Return ``(updated claim, history notes)`` after a scored prediction.

    Works on any dataclass with source_layer, horizon, confidence, status,
    hit_streak, scored, hits and always_hit.
    """
    if claim.status == Status.RETIRED:
        return claim, []
    notes: list[str] = []
    flagged = claim.always_hit
    if (not flagged and claim.scored >= FLAG_MIN_SCORED
            and claim.hits / claim.scored > FLAG_HIT_RATE):
        flagged = True
        notes.append(
            f"always-hit flag set: {claim.hits}/{claim.scored} scored predictions hit, "
            "ranges are uninformative; hits no longer raise confidence"
        )
    if hit:
        confidence = claim.confidence if flagged else min(CONF_MAX, claim.confidence + HIT_STEP)
        streak = claim.hit_streak + 1
    else:
        confidence = max(CONF_MIN, claim.confidence - MISS_STEP)
        streak = 0
    layer = claim.source_layer
    status = claim.status
    horizon = Horizon(claim.horizon)
    if layer == SourceLayer.PRIOR and streak >= PROMOTE_AFTER:
        if horizon == Horizon.SEASON:
            if streak == PROMOTE_AFTER:
                notes.append(
                    f"promotion refused: season-horizon claim stays prior after {streak} hits"
                )
        else:
            layer = SourceLayer.OBSERVED
    if layer != SourceLayer.OBSERVED:
        confidence = min(confidence, PRIOR_CAP)
    confidence = min(confidence, HORIZON_CAP[horizon])
    confidence = round(confidence, 3)
    if confidence < RETIRE_BELOW:
        status = Status.RETIRED
    updated = replace(
        claim, confidence=confidence, hit_streak=streak, source_layer=layer, status=status,
        scored=claim.scored + 1, hits=claim.hits + (1 if hit else 0), always_hit=flagged,
    )
    return updated, notes
