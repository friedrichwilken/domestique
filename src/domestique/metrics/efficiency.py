"""Efficiency factor, decoupling, normalized power, watts at an HR band."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean
from typing import NamedTuple

from domestique.metrics.types import Sample

# Pw:Hr decoupling compares two halves, so it needs at least two samples.
MIN_DECOUPLING_SAMPLES = 2


class _Paired(NamedTuple):
    """A sample that has both power and a positive heart rate."""

    t_s: float
    watts: float
    hr: float


def _valid(samples: Sequence[Sample]) -> list[_Paired]:
    """Samples with both power and a positive heart rate."""
    return [
        _Paired(s["t_s"], w, hr)
        for s in samples
        if (w := s.get("watts")) is not None and (hr := s.get("hr") or 0) > 0
    ]


def _rolling_np(watts: Sequence[float], window_s: int) -> float | None:
    """Coggan NP over a power series; None when shorter than one window."""
    if len(watts) < window_s:
        return None
    total = sum(watts[:window_s])
    rolled = [total / window_s]
    for i in range(window_s, len(watts)):
        total += watts[i] - watts[i - window_s]
        rolled.append(total / window_s)
    return float(fmean(r**4 for r in rolled) ** 0.25)


def normalized_power(samples: Sequence[Sample], window_s: int = 30) -> float | None:
    """Coggan NP: 4th-power mean of a trailing ``window_s`` rolling average.

    Assumes ~1 Hz samples ordered by ``t_s``; gaps are not interpolated.
    Returns None for rides shorter than one window.
    """
    return _rolling_np([w for s in samples if (w := s.get("watts")) is not None], window_s)


def efficiency_factor(samples: Sequence[Sample]) -> float | None:
    """EF = normalized power / average HR (W per bpm)."""
    valid = _valid(samples)
    np_w = _rolling_np([p.watts for p in valid], 30)
    if np_w is None:
        return None
    return np_w / fmean(p.hr for p in valid)


def decoupling_pct(samples: Sequence[Sample]) -> float | None:
    """Pw:Hr decoupling, percent.

    (W/HR first half - W/HR second half) / W/HR first half * 100, where each
    half is split at the midpoint of elapsed time and W/HR is mean watts over
    mean HR. Positive means HR drifted up relative to power.
    """
    valid = _valid(samples)
    if len(valid) < MIN_DECOUPLING_SAMPLES:
        return None
    mid = (valid[0].t_s + valid[-1].t_s) / 2
    first = [p for p in valid if p.t_s < mid]
    second = [p for p in valid if p.t_s >= mid]
    if not first or not second:
        return None
    eff1 = fmean(p.watts for p in first) / fmean(p.hr for p in first)
    eff2 = fmean(p.watts for p in second) / fmean(p.hr for p in second)
    if eff1 == 0:
        return None
    return (eff1 - eff2) / eff1 * 100


def watts_at_hr_band(samples: Sequence[Sample], hr_low: float, hr_high: float) -> float | None:
    """Mean power over samples with ``hr_low <= hr <= hr_high``; None if no samples."""
    inband = [
        w
        for s in samples
        if (w := s.get("watts")) is not None
        and (hr := s.get("hr")) is not None
        and hr_low <= hr <= hr_high
    ]
    return fmean(inband) if inband else None
