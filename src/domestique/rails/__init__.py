"""Safety rails: pure functions nobody overrides from inside the system.

Every rail shares one signature, ``(day, baselines, limits) -> RailResult | None``,
and triggering produces referral wording, never training advice.
"""

from domestique.rails.registry import (
    DEFAULT_LIMITS,
    RAILS,
    DayData,
    Limits,
    RailResult,
    evaluate,
    hrv_floor,
    illness,
    joint_pain,
    limits_from_intent,
    ramp_ceiling,
)

__all__ = [
    "DEFAULT_LIMITS",
    "RAILS",
    "DayData",
    "Limits",
    "RailResult",
    "evaluate",
    "hrv_floor",
    "illness",
    "joint_pain",
    "limits_from_intent",
    "ramp_ceiling",
]
