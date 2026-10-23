"""Plain-data shapes shared by the metric functions."""

from __future__ import annotations

from typing import TypedDict


class Sample(TypedDict, total=False):
    """One recorded sample. ``lr`` is the left-leg share of power, percent; values may be None."""

    t_s: float
    watts: float | None
    hr: float | None
    cadence: float | None
    lr: float | None
    temp: float | None


class Interval(TypedDict):
    """Where an interval sits in the ride, in elapsed seconds."""

    start_s: float
    dur_s: float
