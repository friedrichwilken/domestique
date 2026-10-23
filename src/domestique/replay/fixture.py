"""The fixture season as a ``SeasonSource``, from ``evals/fixtures/season_a/generate.py``.

Rides are stored as constant-value blocks ``[seconds, watts, hr]`` and expanded
here to 1 Hz samples, once per ride.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path

from domestique.ingest.plan_store import PlannedSession, WorkInterval
from domestique.metrics.types import Sample
from domestique.replay.source import Night, Ride

SECONDS_PER_HOUR = 3600.0
SEGMENT_FIELDS = 3  # [seconds, watts, hr]


def _obj(raw: object, what: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{what} must be an object, got {type(raw).__name__}")
    return {str(k): v for k, v in raw.items()}


def _rows(raw: object, what: str) -> list[Mapping[str, object]]:
    if not isinstance(raw, list):
        raise TypeError(f"{what} must be a list")
    return [_obj(r, f"{what}[{i}]") for i, r in enumerate(raw)]


def _num(raw: object) -> float | None:
    if raw is None:
        return None
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        raise TypeError(f"expected a number, got {raw!r}")
    return float(raw)


def _req(raw: object) -> float:
    value = _num(raw)
    if value is None:
        raise TypeError("expected a number, got null")
    return value


def _int(raw: object) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise TypeError(f"expected an integer, got {raw!r}")
    return raw


def _opt_int(raw: object) -> int | None:
    return None if raw is None else _int(raw)


def _opt_str(raw: object) -> str | None:
    return None if raw is None else str(raw)


def _read(path: Path) -> object:
    result: object = json.loads(path.read_text())
    return result


def _session(r: Mapping[str, object]) -> PlannedSession:
    start = _opt_str(r.get("start_local"))
    return PlannedSession(
        id=_int(r["id"]),
        date=date.fromisoformat(str(r["date"])),
        start_local=None if start is None else datetime.fromisoformat(start),
        sport=_opt_str(r.get("sport")),
        title=_opt_str(r.get("title")),
        description=_opt_str(r.get("description")),
        planned_tss=_num(r.get("planned_tss")),
        planned_if=_num(r.get("planned_if")),
        paired_activity_id=_opt_int(r.get("paired_activity_id")),
    )


def _work(raw: object) -> tuple[WorkInterval, ...]:
    rows = _rows(raw or [], "intervals")
    return tuple(
        WorkInterval(_num(iv.get("dur_s")), _num(iv.get("avg_hr")))
        for iv in rows
        if str(iv.get("kind", "")).upper() == "WORK"
    )


def _ride(r: Mapping[str, object]) -> Ride:
    return Ride(
        id=_int(r["id"]),
        sport=_opt_str(r.get("sport")),
        start_local=datetime.fromisoformat(str(r["start_local"])),
        max_hr=_num(r.get("max_hr")),
        work_intervals=_work(r.get("intervals")),
    )


def expand(segments: object) -> list[Sample]:
    """Constant-value blocks ``[seconds, watts, hr]`` to 1 Hz samples."""
    if not isinstance(segments, list):
        raise TypeError("segments must be a list")
    out: list[Sample] = []
    for block in segments:
        if not isinstance(block, list) or len(block) != SEGMENT_FIELDS:
            raise TypeError(f"segment must be [seconds, watts, hr], got {block!r}")
        secs, watts, hr = int(_req(block[0])), _num(block[1]), _num(block[2])
        t0 = len(out)
        out.extend({"t_s": float(t0 + i), "watts": watts, "hr": hr} for i in range(secs))
    return out


def _night(r: Mapping[str, object]) -> Night:
    sleep_s = _num(r.get("sleep_s"))
    return Night(
        date=date.fromisoformat(str(r["date"])),
        hrv=_num(r.get("hrv")),
        sleep_h=None if sleep_s is None else sleep_s / SECONDS_PER_HOUR,
    )


class FixtureSeason:
    """A season from ``meta.json``, ``planned.json``, ``activities.json``, ``wellness.json``."""

    def __init__(self, directory: Path) -> None:
        meta = _obj(_read(directory / "meta.json"), "meta.json")
        self.athlete_id = str(meta["athlete_id"])
        self.hr_max: float | None = _num(meta.get("hr_max"))
        self.first = date.fromisoformat(str(meta["start"]))
        self.last = self.first + timedelta(days=_int(meta["days"]) - 1)
        self._planned = [_session(r) for r in _rows(_read(directory / "planned.json"), "planned")]
        raw_rides = _rows(_read(directory / "activities.json"), "activities")
        self._rides = sorted((_ride(r) for r in raw_rides), key=lambda r: r.start_local)
        self._by_id = {r.id: r for r in self._rides}
        self._segments = {_int(r["id"]): r.get("segments") for r in raw_rides}
        self._samples: dict[int, list[Sample]] = {}
        nights = (_night(r) for r in _rows(_read(directory / "wellness.json"), "wellness"))
        self._nights = {n.date: n for n in nights}

    def planned_on(self, day: date) -> list[PlannedSession]:
        return sorted((s for s in self._planned if s.date == day), key=lambda s: s.id)

    def rides(self, oldest: date, newest: date) -> list[Ride]:
        found = [r for r in self._rides if oldest <= r.start_local.date() <= newest]
        return found[::-1]

    def ride(self, activity_id: int) -> Ride | None:
        return self._by_id.get(activity_id)

    def samples(self, activity_id: int) -> list[Sample]:
        if activity_id not in self._segments:
            return []
        if activity_id not in self._samples:
            self._samples[activity_id] = expand(self._segments[activity_id])
        return self._samples[activity_id]

    def nights(self, oldest: date, newest: date) -> list[Night]:
        days = (newest - oldest).days
        found = (self._nights.get(newest - timedelta(days=i)) for i in range(days + 1))
        return [n for n in found if n is not None]
