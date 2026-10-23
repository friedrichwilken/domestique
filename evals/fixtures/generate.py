"""Generate the synthetic fixture rides. Deterministic; no real athlete data.

Run: python evals/fixtures/generate.py
Writes columnar JSON (1 Hz) next to this file.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).parent


def _round(xs, n=2):
    return [round(x, n) for x in xs]


def endurance_3h() -> dict:
    """Steady 3 h ride, ~200 W, HR drifts +1.0% relative to power (decoupling ~1%)."""
    n = 3 * 3600
    half = n // 2
    t = list(range(n))
    # Whole sine periods per half so both halves have identical mean power.
    watts = [200 + 15 * math.sin(2 * math.pi * s / 600) for s in t]
    hr = [(130.0 if s < half else 131.3) + 2 * math.sin(2 * math.pi * s / 900) for s in t]
    return {
        "name": "synthetic steady endurance 3h",
        "start_local": "2026-09-05T08:00:00",
        "t_s": t,
        "watts": _round(watts),
        "hr": _round(hr),
        "cadence": [88] * n,
        "lr": [50.0] * n,
        "intervals": [],
        "expected": {"decoupling_pct": 1.0},
    }


def intervals_6x5() -> dict:
    """15 min warm-up, 6 x 5 min @ 330 W with 3 min rests, 10 min cool-down.

    Left-leg share on the reps drifts 63 -> 59 percent; rests sit at 50.
    """
    watts: list[float] = []
    hr: list[float] = []
    lr: list[float] = []
    intervals: list[dict] = []

    def block(secs: int, w: float, h: float, l_share: float):
        watts.extend([w] * secs)
        hr.extend([h] * secs)
        lr.extend([l_share] * secs)

    block(15 * 60, 180, 125, 50.0)
    for i in range(6):
        start = len(watts)
        block(5 * 60, 330, 160 + 3 * i, 63.0 - 0.8 * i)
        intervals.append(
            {
                "idx": i,
                "kind": "WORK",
                "start_s": start,
                "dur_s": 5 * 60,
                "expected_lr": round(63.0 - 0.8 * i, 1),
            }
        )
        if i < 5:
            block(3 * 60, 120, 140, 50.0)
    block(10 * 60, 130, 120, 50.0)
    n = len(watts)
    return {
        "name": "synthetic 6x5min intervals",
        "start_local": "2026-09-08T17:30:00",
        "t_s": list(range(n)),
        "watts": watts,
        "hr": hr,
        "cadence": [92] * n,
        "lr": _round(lr),
        "intervals": intervals,
        "expected": {},
    }


def main():
    for name, ride in (("endurance_3h", endurance_3h()), ("intervals_6x5", intervals_6x5())):
        (HERE / f"{name}.json").write_text(json.dumps(ride, separators=(",", ":")))
        print("wrote", name)


if __name__ == "__main__":
    main()
