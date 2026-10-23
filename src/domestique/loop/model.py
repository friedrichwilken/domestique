"""Plain data shared by the predictor, the scorer and their stores. No I/O.

A *binding* is the machine-readable rule that lets a claim feed one metric.
Claims are prose; the predictor only uses claims that carry a binding for the
metric at hand, so a claim without one informs nothing.

Every metric is computed from a base value the same way:

    expected = base * (1 + change_pct / 100) + offset
    range    = expected -/+ (expected * range_pct / 100 + range_abs)

The base depends on the metric (see ``predict.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from domestique.metrics.types import Sample


class Metric(StrEnum):
    WATTS_AT_HR = "watts_at_hr"
    PEAK_HR = "peak_hr"
    HRV_NEXT_MORNING = "hrv_next_morning"
    SLEEP_HOURS = "sleep_hours"


HOURS_PER_DAY = 24
DEFAULT_RIDES = 3
BASELINE_NIGHTS = 28  # nights a history-derived baseline looks back
_CONDITION_KEYS = frozenset({"min_if", "max_if", "sports", "start_hour_from", "start_hour_to"})
_PARAM_KEYS = frozenset({"change_pct", "offset", "range_pct", "range_abs", "rides"})


@dataclass(frozen=True)
class Conditions:
    """When a binding applies. Every field is optional; unset means no restriction.

    ``start_hour_from``/``start_hour_to`` are the athlete's local hours, half-open
    ``[from, to)``, wrapping past midnight when ``from > to``. A session without a
    planned start time never matches a time-of-day condition; one without a planned
    intensity factor never matches an intensity condition.
    """

    min_if: float | None = None
    max_if: float | None = None
    sports: tuple[str, ...] = ()
    start_hour_from: int | None = None
    start_hour_to: int | None = None

    def __post_init__(self) -> None:
        for name in ("start_hour_from", "start_hour_to"):
            hour = getattr(self, name)
            if hour is not None and not 0 <= hour < HOURS_PER_DAY:
                raise ValueError(f"conditions.{name} must be an hour 0-23, got {hour}")
        if (self.start_hour_from is None) != (self.start_hour_to is None):
            raise ValueError("conditions.start_hour_from and start_hour_to go together")


@dataclass(frozen=True)
class Binding:
    claim_id: str
    metric: Metric
    change_pct: float = 0.0
    offset: float = 0.0
    range_pct: float = 0.0
    range_abs: float = 0.0
    rides: int = DEFAULT_RIDES  # watts_at_hr only: how many recent rides form the base
    when: Conditions = field(default_factory=Conditions)

    def __post_init__(self) -> None:
        if self.range_pct < 0 or self.range_abs < 0:
            raise ValueError("binding range_pct and range_abs must not be negative")
        if self.range_pct == 0 and self.range_abs == 0:
            raise ValueError("binding needs a range: a zero-width range is not a prediction")
        if self.rides < 1:
            raise ValueError("binding rides must be at least 1")


def _unknown(keys: Mapping[str, object], allowed: frozenset[str], what: str) -> None:
    extra = sorted(set(keys) - allowed)
    if extra:
        raise ValueError(f"unknown {what} field(s): {', '.join(extra)}")


def _opt_float(raw: Mapping[str, object], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise TypeError(f"{key} must be a number, got {value!r}")
    return float(value)


def _opt_int(raw: Mapping[str, object], key: str) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{key} must be an integer, got {value!r}")
    return value


def _or[T](value: T | None, default: T) -> T:
    return default if value is None else value


def parse_conditions(raw: Mapping[str, object]) -> Conditions:
    _unknown(raw, _CONDITION_KEYS, "conditions")
    sports = raw.get("sports") or ()
    if not isinstance(sports, list | tuple) or not all(isinstance(s, str) for s in sports):
        raise TypeError(f"conditions.sports must be a list of strings, got {sports!r}")
    return Conditions(
        min_if=_opt_float(raw, "min_if"),
        max_if=_opt_float(raw, "max_if"),
        sports=tuple(str(s) for s in sports),
        start_hour_from=_opt_int(raw, "start_hour_from"),
        start_hour_to=_opt_int(raw, "start_hour_to"),
    )


def parse_binding(
    claim_id: str,
    metric: str,
    params: Mapping[str, object],
    conditions: Mapping[str, object],
) -> Binding:
    """A binding from stored JSON; unknown fields and wrong types are rejected."""
    _unknown(params, _PARAM_KEYS, "binding params")
    return Binding(
        claim_id=claim_id,
        metric=Metric(metric),
        change_pct=_or(_opt_float(params, "change_pct"), 0.0),
        offset=_or(_opt_float(params, "offset"), 0.0),
        range_pct=_or(_opt_float(params, "range_pct"), 0.0),
        range_abs=_or(_opt_float(params, "range_abs"), 0.0),
        rides=_or(_opt_int(params, "rides"), DEFAULT_RIDES),
        when=parse_conditions(conditions),
    )


def binding_params(b: Binding) -> dict[str, float | int]:
    return {
        "change_pct": b.change_pct,
        "offset": b.offset,
        "range_pct": b.range_pct,
        "range_abs": b.range_abs,
        "rides": b.rides,
    }


def conditions_json(c: Conditions) -> dict[str, object]:
    out: dict[str, object] = {
        "min_if": c.min_if,
        "max_if": c.max_if,
        "sports": list(c.sports) or None,
        "start_hour_from": c.start_hour_from,
        "start_hour_to": c.start_hour_to,
    }
    return {k: v for k, v in out.items() if v is not None}


# JSON-friendly values recorded with a prediction.
type Basis = dict[str, object]


@dataclass(frozen=True)
class Prediction:
    """One claim's prediction for a session and metric.

    ``official`` marks the one the precedence rule picked, the prediction that is
    reported; the others are shadows, scored the same way.
    """

    planned_session_id: int
    metric: Metric
    expected: float
    low: float
    high: float
    claim_ids: tuple[str, ...]
    basis: Basis = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    official: bool = True

    @property
    def claim_id(self) -> str:
        return self.claim_ids[0]

    @property
    def half_range(self) -> float:
        return (self.high - self.low) / 2

    def hit(self, actual: float) -> bool:
        return self.low <= actual <= self.high


@dataclass(frozen=True)
class Gap:
    """A metric left unpredicted, and why."""

    planned_session_id: int
    metric: Metric
    reason: str


@dataclass(frozen=True)
class PredictionSet:
    predictions: tuple[Prediction, ...]  # official and shadow
    gaps: tuple[Gap, ...]

    @property
    def official(self) -> tuple[Prediction, ...]:
        return tuple(p for p in self.predictions if p.official)


@dataclass(frozen=True)
class RideSamples:
    activity_id: int
    samples: Sequence[Sample]


@dataclass(frozen=True)
class History:
    """What the predictor may look at, all strictly before the session.

    ``rides`` are earlier rides of the session's sport family, newest first.
    ``hrv`` and ``sleep_h`` are recent nightly values, newest first; they stand in
    for a baseline the configuration does not give.
    """

    hr_max: float | None
    baselines: Mapping[str, float] = field(default_factory=dict)
    rides: tuple[RideSamples, ...] = ()
    hrv: tuple[float, ...] = ()
    sleep_h: tuple[float, ...] = ()


@dataclass(frozen=True)
class Actuals:
    """What happened: the paired ride (None when not ridden) and the next morning."""

    activity_id: int | None
    samples: Sequence[Sample] = ()
    max_hr: float | None = None
    hrv_next_morning: float | None = None
    sleep_hours: float | None = None


@dataclass(frozen=True)
class Outcome:
    prediction_id: str
    actual: float
    error: float  # actual - expected
