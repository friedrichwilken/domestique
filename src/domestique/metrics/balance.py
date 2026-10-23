"""Left/right power balance, whole ride and per interval."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean

from domestique.metrics.types import Interval, Sample


def lr_balance(samples: Sequence[Sample]) -> float | None:
    """Mean left-leg share (percent) over samples that report it."""
    vals = [lr for s in samples if (lr := s.get("lr")) is not None]
    return fmean(vals) if vals else None


def interval_lr_balance(
    samples: Sequence[Sample], intervals: Sequence[Interval]
) -> list[float | None]:
    """Left-leg share per interval, from samples in [start_s, start_s + dur_s)."""
    out: list[float | None] = []
    for iv in intervals:
        lo, hi = iv["start_s"], iv["start_s"] + iv["dur_s"]
        out.append(lr_balance([s for s in samples if lo <= s["t_s"] < hi]))
    return out
