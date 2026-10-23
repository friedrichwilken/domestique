"""Pair planned sessions with executed activities.

Rule: same local date and sport family, closest start time wins, each planned
session takes at most one activity and each activity serves at most one plan.
Unpaired plans are reported as missed; nothing is ever deleted.
Pure functions only, no database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

# Platform sport types that count as the same sport for pairing: a planned
# "Ride" ridden on the trainer arrives as "VirtualRide".
SPORT_FAMILY: dict[str, str] = {
    "Ride": "Ride",
    "VirtualRide": "Ride",
    "GravelRide": "Ride",
    "MountainBikeRide": "Ride",
    "EBikeRide": "Ride",
    "EMountainBikeRide": "Ride",
    "TrackRide": "Ride",
    "Velomobile": "Ride",
    "Run": "Run",
    "VirtualRun": "Run",
    "TrailRun": "Run",
    "Swim": "Swim",
    "OpenWaterSwim": "Swim",
}


def sport_family(sport: str | None) -> str | None:
    if sport is None:
        return None
    return SPORT_FAMILY.get(sport, sport)


@dataclass(frozen=True)
class PlanRef:
    id: int
    date: date
    sport: str | None
    start_local: datetime | None


@dataclass(frozen=True)
class ActivityRef:
    id: int
    sport: str | None
    start_local: datetime


@dataclass(frozen=True)
class Pairing:
    paired: dict[int, int]  # planned session id -> activity id
    missed: tuple[int, ...]  # planned session ids with no activity


def _plan_start(plan: PlanRef) -> datetime:
    """An untimed plan sits at local midnight, so ties fall back to plan order."""
    if plan.start_local is not None:
        return plan.start_local
    return datetime.combine(plan.date, datetime.min.time())


def _candidates(
    plans: Sequence[PlanRef], activities: Sequence[ActivityRef]
) -> list[tuple[float, int, datetime, PlanRef, ActivityRef]]:
    """Every same-day, same-sport (plan, activity) combination, closest first."""
    out = []
    for order, plan in enumerate(plans):
        start = _plan_start(plan)
        family = sport_family(plan.sport)
        for act in activities:
            if act.start_local.date() != plan.date or sport_family(act.sport) != family:
                continue
            gap = abs((act.start_local - start).total_seconds())
            out.append((gap, order, act.start_local, plan, act))
    out.sort(key=lambda c: (c[0], c[1], c[2]))
    return out


def pair(plans: Sequence[PlanRef], activities: Sequence[ActivityRef]) -> Pairing:
    """Greedy closest-start matching; deterministic for ties (plan order, then ride start)."""
    ordered = sorted(plans, key=lambda p: (p.date, _plan_start(p), p.id))
    paired: dict[int, int] = {}
    used: set[int] = set()
    for _, _, _, plan, act in _candidates(ordered, activities):
        if plan.id in paired or act.id in used:
            continue
        paired[plan.id] = act.id
        used.add(act.id)
    missed = tuple(p.id for p in ordered if p.id not in paired)
    return Pairing(paired=paired, missed=missed)
