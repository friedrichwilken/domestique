"""Generate the synthetic 12-week fixture season 'season_a'. Deterministic; no real athlete data.

Run: python evals/fixtures/season_a/generate.py
Writes meta.json, planned.json, activities.json and wellness.json next to this
file. Same seed, same bytes: the test suite regenerates into a scratch
directory and compares.

The synthetic athlete
- max HR 190; power at a heart rate follows ``3.0 * (hr - 60)`` watts, scaled
  by a fitness factor that rises 3% over the season and by a small daily form
  noise.
- Week: rest Monday and Friday, hard sessions Tuesday and Thursday (threshold
  intervals, planned IF 0.88), endurance Wednesday and Sunday, a long ride on
  Saturday morning. Hard and Wednesday sessions start in the evening (18:30)
  or the morning (07:00) at random. About one session in twenty is missed.
- Sleep is 7.6 h with 0.2 h of night-to-night noise.

The planted effect: a hard session ridden in the evening costs one hour of
sleep that night (``EVENING_SLEEP_COST_H``). Evening endurance rides and
morning hard sessions cost nothing. Next-morning HRV falls about 8% after a
hard session, a little after the long ride.

Rides are stored as constant-value blocks ``[seconds, watts, hr]`` (a
run-length-encoded 1 Hz stream), which the replay expands back to samples.
Wellness on date D is the morning reading of D: the night from D-1 to D.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

HERE = Path(__file__).parent
SEED = 20260105
START = date(2026, 1, 5)  # a Monday
WEEKS = 12
DAYS = WEEKS * 7
HR_MAX = 190
ATHLETE = "athlete-synth-season-a"
EVENING_SLEEP_COST_H = 1.0
SLEEP_MEAN_H = 7.6
SLEEP_NOISE_H = 0.2
HRV_MEAN = 80.0
HARD_HRV_DROP = 0.08
LONG_HRV_DROP = 0.04
MISS_P = 0.05
EVENING_P = 0.6
FITNESS_GAIN = 0.03
EVENING = time(18, 30)
MORNING = time(7, 0)
FIRST_ACTIVITY_ID = 1001

ENDURANCE_TEXT = "60-70% of max heart rate"
HARD_TEXT = "4x8 min threshold, work intervals at 85-92% of max heart rate"


@dataclass(frozen=True)
class Kind:
    name: str
    title: str
    description: str
    planned_if: float
    planned_tss: float
    minutes: int


HARD = Kind("hard", "Threshold 4x8", HARD_TEXT, 0.88, 85.0, 75)
ENDURANCE = Kind("endurance", "Endurance", f"Endurance ride, {ENDURANCE_TEXT}", 0.65, 60.0, 90)
LONG = Kind("long", "Long ride", f"Long endurance ride, {ENDURANCE_TEXT}", 0.68, 170.0, 180)

# weekday (Monday = 0) -> session kind and whether its start time is drawn
WEEK: dict[int, tuple[Kind, bool]] = {
    1: (HARD, True),
    2: (ENDURANCE, True),
    3: (HARD, True),
    5: (LONG, False),
    6: (ENDURANCE, False),
}

type Block = list[float]


def watts_at(hr: float, fitness: float, form: float) -> float:
    return 3.0 * (hr - 60.0) * fitness * form


class Season:
    def __init__(self, seed: int = SEED) -> None:
        self.rng = random.Random(seed)
        self.planned: list[dict[str, object]] = []
        self.activities: list[dict[str, object]] = []
        self.wellness: list[dict[str, object]] = []
        self.after: dict[date, tuple[str, datetime]] = {}  # ridden day -> (kind, start)

    def _block(self, secs: int, hr: float, fitness: float, form: float) -> Block:
        watts = watts_at(hr, fitness, form) + self.rng.gauss(0, 3)
        return [secs, round(watts, 1), round(hr, 1)]

    def _endurance_blocks(self, minutes: int, fitness: float, form: float) -> list[Block]:
        blocks = [self._block(600, 108.0, fitness, form)]
        for _ in range((minutes - 20) // 5):
            hr = min(131.0, max(116.0, self.rng.gauss(124.0, 3.0)))
            blocks.append(self._block(300, hr, fitness, form))
        blocks.append(self._block(600, 104.0, fitness, form))
        return blocks

    def _hard_blocks(
        self, fitness: float, form: float
    ) -> tuple[list[Block], list[dict[str, object]]]:
        blocks = [self._block(900, 122.0, fitness, form)]
        intervals: list[dict[str, object]] = []
        t = 900
        for rep in range(4):
            hr = min(174.0, 166.0 + 2.0 * rep + self.rng.gauss(0, 1.0))
            block = self._block(480, hr, fitness, form)
            blocks.append(block)
            intervals.append(
                {
                    "idx": rep,
                    "kind": "WORK",
                    "start_s": t,
                    "dur_s": 480,
                    "avg_w": block[1],
                    "avg_hr": block[2],
                }
            )
            t += 480
            if rep < 3:
                blocks.append(self._block(240, 135.0, fitness, form))
                t += 240
        blocks.append(self._block(600, 115.0, fitness, form))
        return blocks, intervals

    def _ride(self, pid: int, kind: Kind, start: datetime, day_index: int) -> dict[str, object]:
        fitness = 1.0 + FITNESS_GAIN * day_index / DAYS
        form = 1.0 + self.rng.gauss(0, 0.02)
        intervals: list[dict[str, object]] = []
        if kind is HARD:
            blocks, intervals = self._hard_blocks(fitness, form)
            max_hr = max(b[2] for b in blocks) + self.rng.gauss(6.0, 3.5)
        else:
            blocks = self._endurance_blocks(kind.minutes, fitness, form)
            max_hr = self.rng.gauss(139.0, 3.5)
        aid = FIRST_ACTIVITY_ID + len(self.activities)
        return {
            "id": aid,
            "planned_id": pid,
            "sport": "Ride",
            "start_local": (start + timedelta(minutes=self.rng.randint(0, 15))).isoformat(),
            "moving_s": int(sum(b[0] for b in blocks)),
            "max_hr": round(max_hr, 1),
            "segments": blocks,
            "intervals": intervals,
        }

    def _start(self, day: date, drawn: bool) -> datetime:
        if drawn and self.rng.random() < EVENING_P:
            return datetime.combine(day, EVENING)
        return datetime.combine(day, MORNING)

    def plan_day(self, day_index: int) -> None:
        day = START + timedelta(days=day_index)
        slot = WEEK.get(day.weekday())
        if slot is None:
            return
        kind, drawn = slot
        start = self._start(day, drawn)
        pid = len(self.planned) + 1
        ridden = self.rng.random() >= MISS_P
        ride = self._ride(pid, kind, start, day_index) if ridden else None
        if ride is not None:
            self.activities.append(ride)
            self.after[day] = (kind.name, start)
        self.planned.append(
            {
                "id": pid,
                "date": day.isoformat(),
                "start_local": start.isoformat(),
                "sport": "Ride",
                "title": kind.title,
                "description": kind.description,
                "planned_if": kind.planned_if,
                "planned_tss": kind.planned_tss,
                "planned_moving_s": kind.minutes * 60,
                "paired_activity_id": None if ride is None else ride["id"],
            }
        )

    def morning(self, day: date) -> None:
        kind, start = self.after.get(day - timedelta(days=1), ("rest", None))
        sleep = SLEEP_MEAN_H + self.rng.gauss(0, SLEEP_NOISE_H)
        if kind == "hard" and start is not None and start.time() == EVENING:
            sleep -= EVENING_SLEEP_COST_H
        drop = {"hard": HARD_HRV_DROP, "long": LONG_HRV_DROP}.get(kind, 0.0)
        hrv = HRV_MEAN * (1 - drop) * (1 + self.rng.gauss(0, 0.04))
        rhr = 50.0 + (2.0 if kind == "hard" else 0.0) + self.rng.gauss(0, 1.5)
        self.wellness.append(
            {
                "date": day.isoformat(),
                "hrv": round(hrv, 1),
                "rhr": round(rhr, 1),
                "sleep_s": round(sleep * 3600),
            }
        )


def build(seed: int = SEED) -> Season:
    s = Season(seed)
    for i in range(DAYS):
        s.plan_day(i)
    for i in range(DAYS + 1):  # the last morning scores the last day
        s.morning(START + timedelta(days=i))
    return s


def _records(rows: list[dict[str, object]]) -> str:
    """One JSON record per line: diffs stay reviewable, bytes stay stable."""
    body = ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return f"[\n{body}\n]\n"


def write(out: Path, seed: int = SEED) -> list[Path]:
    s = build(seed)
    meta = {
        "athlete_id": ATHLETE,
        "hr_max": HR_MAX,
        "start": START.isoformat(),
        "days": DAYS,
        "seed": seed,
        "planted_effect": {
            "description": "a hard session (planned IF >= 0.85) started in the evening "
            "costs about one hour of sleep that night",
            "sleep_cost_h": EVENING_SLEEP_COST_H,
            "min_if": 0.85,
            "start_hour_from": 17,
            "start_hour_to": 23,
        },
    }
    files = {
        "meta.json": json.dumps(meta, sort_keys=True, indent=2) + "\n",
        "planned.json": _records(s.planned),
        "activities.json": _records(s.activities),
        "wellness.json": _records(s.wellness),
    }
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in files.items():
        path = out / name
        path.write_text(text)
        written.append(path)
    return written


def main() -> None:
    for path in write(HERE):
        print("wrote", path.name)


if __name__ == "__main__":
    main()
