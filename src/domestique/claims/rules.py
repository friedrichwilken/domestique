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
- Retired claims are never adjusted (they are no longer tested).
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


class SourceLayer(StrEnum):
    OBSERVED = "observed"
    STATED = "stated"
    PRIOR = "prior"


class Status(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    CANDIDATE = "candidate"


def adjust_confidence(claim, hit: bool):
    """Return an updated copy of ``claim`` (dataclass) after a scored prediction.

    Works on any dataclass with source_layer, confidence, status, hit_streak.
    """
    if claim.status == Status.RETIRED:
        return claim
    if hit:
        confidence = min(CONF_MAX, claim.confidence + HIT_STEP)
        streak = claim.hit_streak + 1
    else:
        confidence = max(CONF_MIN, claim.confidence - MISS_STEP)
        streak = 0
    layer = claim.source_layer
    status = claim.status
    if layer == SourceLayer.PRIOR and streak >= PROMOTE_AFTER:
        layer = SourceLayer.OBSERVED
    if layer != SourceLayer.OBSERVED:
        confidence = min(confidence, PRIOR_CAP)
    confidence = round(confidence, 3)
    if confidence < RETIRE_BELOW:
        status = Status.RETIRED
    return replace(claim, confidence=confidence, hit_streak=streak,
                   source_layer=layer, status=status)
