"""Efficiency factor, decoupling, normalized power, watts at an HR band."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean


def _valid(samples: Sequence[dict]) -> list[dict]:
    """Samples with both power and a positive heart rate."""
    return [s for s in samples if s.get("watts") is not None and (s.get("hr") or 0) > 0]


def normalized_power(samples: Sequence[dict], window_s: int = 30) -> float | None:
    """Coggan NP: 4th-power mean of a trailing ``window_s`` rolling average.

    Assumes ~1 Hz samples ordered by ``t_s``; gaps are not interpolated.
    Returns None for rides shorter than one window.
    """
    watts = [s["watts"] for s in samples if s.get("watts") is not None]
    if len(watts) < window_s:
        return None
    total = sum(watts[:window_s])
    rolled = [total / window_s]
    for i in range(window_s, len(watts)):
        total += watts[i] - watts[i - window_s]
        rolled.append(total / window_s)
    return fmean(r**4 for r in rolled) ** 0.25


def efficiency_factor(samples: Sequence[dict]) -> float | None:
    """EF = normalized power / average HR (W per bpm)."""
    valid = _valid(samples)
    np_w = normalized_power(valid)
    if np_w is None:
        return None
    return np_w / fmean(s["hr"] for s in valid)


def decoupling_pct(samples: Sequence[dict]) -> float | None:
    """Pw:Hr decoupling, percent.

    (W/HR first half - W/HR second half) / W/HR first half * 100, where each
    half is split at the midpoint of elapsed time and W/HR is mean watts over
    mean HR. Positive means HR drifted up relative to power.
    """
    valid = _valid(samples)
    if len(valid) < 2:
        return None
    t0, t1 = valid[0]["t_s"], valid[-1]["t_s"]
    mid = (t0 + t1) / 2
    first = [s for s in valid if s["t_s"] < mid]
    second = [s for s in valid if s["t_s"] >= mid]
    if not first or not second:
        return None
    eff1 = fmean(s["watts"] for s in first) / fmean(s["hr"] for s in first)
    eff2 = fmean(s["watts"] for s in second) / fmean(s["hr"] for s in second)
    if eff1 == 0:
        return None
    return (eff1 - eff2) / eff1 * 100


def watts_at_hr_band(samples: Sequence[dict], hr_low: float, hr_high: float) -> float | None:
    """Mean power over samples with ``hr_low <= hr <= hr_high``; None if no samples."""
    inband = [
        s["watts"]
        for s in samples
        if s.get("watts") is not None and s.get("hr") is not None and hr_low <= s["hr"] <= hr_high
    ]
    return fmean(inband) if inband else None
