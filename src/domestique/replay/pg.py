"""The athlete's own ingested history as a ``SeasonSource``, read from the configured database.

Read-only by construction: ``open_readonly`` sets the connection read-only
before the first query, so Postgres itself refuses a write from anywhere in
the replay. No migration is run. Queries mirror ``loop.load`` and
``ingest.plan_store``.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, time
from typing import Any

from domestique import db
from domestique.ingest.plan_store import PgPlanStore, PlannedSession
from domestique.loop.load import MAX_RIDES, load_samples
from domestique.metrics.types import Sample
from domestique.replay.source import Night, Ride

SECONDS_PER_HOUR = 3600.0
STREAM_CACHE = 2 * MAX_RIDES + 2  # streams kept in memory: the history window plus the scored ride


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


class PgSeason:
    def __init__(
        self, conn: db.Conn, athlete_id: str, hr_max: float | None, first: date, last: date
    ) -> None:
        self.conn = conn
        self.athlete_id = athlete_id
        self.hr_max = hr_max
        self.first = first
        self.last = last
        self._plans = PgPlanStore(conn)
        self._samples: OrderedDict[int, list[Sample]] = OrderedDict()
        self._rides: dict[int, Ride] = {}

    def planned_on(self, day: date) -> list[PlannedSession]:
        return self._plans.planned_on(self.athlete_id, day)

    def _ride(self, r: tuple[Any, ...]) -> Ride:
        aid = int(r[0])
        if aid not in self._rides:
            executed = self._plans.executed(aid)
            work = executed.work_intervals if executed is not None else ()
            self._rides[aid] = Ride(aid, r[1], r[2], _num(r[3]), work)
        return self._rides[aid]

    def rides(self, oldest: date, newest: date) -> list[Ride]:
        rows = self.conn.execute(
            "SELECT id, sport, start_local, max_hr FROM activities WHERE athlete_id = %s "
            "AND start_local >= %s AND start_local <= %s ORDER BY start_local DESC",
            (
                self.athlete_id,
                datetime.combine(oldest, time.min),
                datetime.combine(newest, time.max),
            ),
        ).fetchall()
        return [self._ride(r) for r in rows]

    def ride(self, activity_id: int) -> Ride | None:
        row = self.conn.execute(
            "SELECT id, sport, start_local, max_hr FROM activities "
            "WHERE id = %s AND athlete_id = %s",
            (activity_id, self.athlete_id),
        ).fetchone()
        return None if row is None else self._ride(row)

    def samples(self, activity_id: int) -> list[Sample]:
        if activity_id in self._samples:
            self._samples.move_to_end(activity_id)
            return self._samples[activity_id]
        found = load_samples(self.conn, activity_id)
        self._samples[activity_id] = found
        if len(self._samples) > STREAM_CACHE:
            self._samples.popitem(last=False)
        return found

    def nights(self, oldest: date, newest: date) -> list[Night]:
        rows = self.conn.execute(
            "SELECT date, hrv, sleep_s FROM wellness WHERE athlete_id = %s "
            "AND date >= %s AND date <= %s ORDER BY date DESC",
            (self.athlete_id, oldest, newest),
        ).fetchall()
        return [
            Night(
                date=r[0],
                hrv=_num(r[1]),
                sleep_h=None if r[2] is None else float(r[2]) / SECONDS_PER_HOUR,
            )
            for r in rows
        ]


def open_readonly(dsn: str | None) -> db.Conn:
    """A connection on which Postgres refuses writes."""
    conn = db.connect(dsn)
    conn.read_only = True
    return conn
