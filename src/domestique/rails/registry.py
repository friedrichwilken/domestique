"""The four rails and their registry.

Thresholds come from ``rails.yaml`` (optional ``threshold`` per rail) and
fall back to the defaults below; the logic and the wording live here, not in
YAML, so no file edit can turn a referral into advice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from domestique.intent.schemas import Rail, RailAction

JOINT_PAIN_TAG = "joint-pain"
ILLNESS_KIND = "illness"


@dataclass(frozen=True)
class DayData:
    """One day's data-plane rows, reduced to what the rails read."""

    date: date
    subjective_tags: tuple[str, ...] = ()
    hrv: float | None = None
    ctl_delta_7d: float | None = None
    context_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class Limits:
    hrv_floor_ratio: float = 0.65  # day's HRV below this share of baseline downgrades the day
    ramp_ceiling_ctl_7d: float = 7.0  # CTL gain over 7 days above this refuses more load


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class RailResult:
    rail: str
    action: RailAction
    wording: str


type RailFn = Callable[[DayData, Mapping[str, float], Limits], RailResult | None]


def joint_pain(
    day: DayData, baselines: Mapping[str, float], limits: Limits = DEFAULT_LIMITS
) -> RailResult | None:
    del baselines, limits  # shared signature; this rail needs neither
    if JOINT_PAIN_TAG not in day.subjective_tags:
        return None
    return RailResult(
        rail="joint-pain",
        action="stop_plan",
        wording=(
            "Joint pain was reported. The plan is paused. "
            "This is a question for your physio or surgeon."
        ),
    )


def hrv_floor(
    day: DayData, baselines: Mapping[str, float], limits: Limits = DEFAULT_LIMITS
) -> RailResult | None:
    baseline = baselines.get("hrv")
    if day.hrv is None or not baseline:
        return None
    floor = limits.hrv_floor_ratio * baseline
    if day.hrv >= floor:
        return None
    return RailResult(
        rail="hrv-floor",
        action="downgrade_day",
        wording=(
            f"HRV today is {day.hrv:.0f}, under the floor of {floor:.0f} "
            f"({limits.hrv_floor_ratio:.0%} of the {baseline:.0f} baseline). The day is downgraded."
        ),
    )


def ramp_ceiling(
    day: DayData, baselines: Mapping[str, float], limits: Limits = DEFAULT_LIMITS
) -> RailResult | None:
    del baselines  # shared signature; the ceiling is absolute
    if day.ctl_delta_7d is None or day.ctl_delta_7d <= limits.ramp_ceiling_ctl_7d:
        return None
    return RailResult(
        rail="ramp-ceiling",
        action="refuse_additional_load",
        wording=(
            f"CTL rose {day.ctl_delta_7d:.1f} over 7 days, above the ceiling of "
            f"{limits.ramp_ceiling_ctl_7d:.1f}. Additional load is refused."
        ),
    )


def illness(
    day: DayData, baselines: Mapping[str, float], limits: Limits = DEFAULT_LIMITS
) -> RailResult | None:
    del baselines, limits  # shared signature; this rail needs neither
    if ILLNESS_KIND not in day.context_kinds:
        return None
    return RailResult(
        rail="illness",
        action="no_intensity",
        wording=(
            "Illness is logged for today. No intensity is planned while it lasts. "
            "The illness itself is a question for a doctor."
        ),
    )


RAILS: dict[str, RailFn] = {
    "joint-pain": joint_pain,
    "hrv-floor": hrv_floor,
    "ramp-ceiling": ramp_ceiling,
    "illness": illness,
}


def limits_from_intent(rails: Sequence[Rail]) -> Limits:
    """Thresholds from ``rails.yaml`` where given, defaults otherwise."""
    limits = DEFAULT_LIMITS
    for rail in rails:
        if rail.threshold is None:
            continue
        if rail.id == "hrv-floor":
            limits = replace(limits, hrv_floor_ratio=rail.threshold)
        elif rail.id == "ramp-ceiling":
            limits = replace(limits, ramp_ceiling_ctl_7d=rail.threshold)
    return limits


def evaluate(
    day: DayData, baselines: Mapping[str, float], limits: Limits = DEFAULT_LIMITS
) -> list[RailResult]:
    """Every rail that triggers on the day, in registry order. Empty on a quiet day."""
    return [r for fn in RAILS.values() if (r := fn(day, baselines, limits)) is not None]
