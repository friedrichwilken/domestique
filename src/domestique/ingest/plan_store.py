"""Storage for planned sessions and their pairing: one interface, Postgres and in-memory.

The in-memory store backs the unit tests; the Postgres store is exercised by
the integration tests when ``DOMESTIQUE_TEST_DSN`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Protocol, TypedDict

from psycopg.types.json import Jsonb

from domestique import db
from domestique.ingest.pairing import ActivityRef, Pairing, PlanRef

WORK_KIND = "WORK"  # intervals.icu marks prescribed efforts as WORK, the rest RECOVERY


class PlannedRow(TypedDict):
    athlete_id: str
    source: str
    external_id: str
    date: date
    start_local: datetime | None
    sport: str | None
    title: str | None
    description: str | None
    structure: Any  # workout steps exactly as the platform returned them, or None
    planned_tss: float | None
    planned_if: float | None
    planned_moving_s: int | None
    raw: Any  # the whole event payload


@dataclass(frozen=True)
class PlannedSession:
    id: int
    date: date
    start_local: datetime | None
    sport: str | None
    title: str | None
    description: str | None
    planned_tss: float | None
    planned_if: float | None
    paired_activity_id: int | None


@dataclass(frozen=True)
class WorkInterval:
    dur_s: float | None
    avg_hr: float | None


@dataclass(frozen=True)
class ExecutedSession:
    id: int
    sport: str | None
    start_local: datetime
    np_w: float | None
    avg_hr: float | None
    max_hr: float | None
    intensity_factor: float | None
    work_intervals: tuple[WorkInterval, ...] = ()


class PlanStore(Protocol):
    def upsert_planned(self, row: PlannedRow) -> int: ...

    def plan_refs(self, athlete_id: str, oldest: date, newest: date) -> list[PlanRef]: ...

    def activity_refs(self, athlete_id: str, oldest: date, newest: date) -> list[ActivityRef]: ...

    def record_pairing(self, athlete_id: str, oldest: date, newest: date, p: Pairing) -> None: ...

    def planned_on(self, athlete_id: str, day: date) -> list[PlannedSession]: ...

    def executed(self, activity_id: int) -> ExecutedSession | None: ...


# --- in memory --------------------------------------------------------------


def _session(pid: int, row: PlannedRow, paired: int | None) -> PlannedSession:
    return PlannedSession(
        id=pid,
        date=row["date"],
        start_local=row["start_local"],
        sport=row["sport"],
        title=row["title"],
        description=row["description"],
        planned_tss=row["planned_tss"],
        planned_if=row["planned_if"],
        paired_activity_id=paired,
    )


@dataclass
class MemoryPlanStore:
    planned: dict[tuple[str, str, str], tuple[int, PlannedRow]] = field(default_factory=dict)
    pairs: dict[int, int] = field(default_factory=dict)
    activities: dict[int, tuple[str, ExecutedSession]] = field(default_factory=dict)

    def add_activity(self, athlete_id: str, session: ExecutedSession) -> None:
        self.activities[session.id] = (athlete_id, session)

    def upsert_planned(self, row: PlannedRow) -> int:
        key = (row["athlete_id"], row["source"], row["external_id"])
        pid = self.planned[key][0] if key in self.planned else len(self.planned) + 1
        self.planned[key] = (pid, row)
        return pid

    def _rows(self, athlete_id: str, oldest: date, newest: date) -> list[tuple[int, PlannedRow]]:
        return [
            (pid, row)
            for pid, row in self.planned.values()
            if row["athlete_id"] == athlete_id and oldest <= row["date"] <= newest
        ]

    def plan_refs(self, athlete_id: str, oldest: date, newest: date) -> list[PlanRef]:
        return [
            PlanRef(pid, row["date"], row["sport"], row["start_local"])
            for pid, row in self._rows(athlete_id, oldest, newest)
        ]

    def activity_refs(self, athlete_id: str, oldest: date, newest: date) -> list[ActivityRef]:
        return [
            ActivityRef(s.id, s.sport, s.start_local)
            for who, s in self.activities.values()
            if who == athlete_id and oldest <= s.start_local.date() <= newest
        ]

    def record_pairing(self, athlete_id: str, oldest: date, newest: date, p: Pairing) -> None:
        for pid, _ in self._rows(athlete_id, oldest, newest):
            self.pairs.pop(pid, None)
        self.pairs.update(p.paired)

    def planned_on(self, athlete_id: str, day: date) -> list[PlannedSession]:
        rows = sorted(self._rows(athlete_id, day, day), key=lambda r: r[0])
        return [_session(pid, row, self.pairs.get(pid)) for pid, row in rows]

    def executed(self, activity_id: int) -> ExecutedSession | None:
        found = self.activities.get(activity_id)
        return found[1] if found else None


# --- Postgres ---------------------------------------------------------------

_UPSERT_PLANNED = """
INSERT INTO planned_sessions (athlete_id, source, external_id, date, start_local, sport,
    title, description, structure, planned_tss, planned_if, planned_moving_s, raw)
VALUES (%(athlete_id)s, %(source)s, %(external_id)s, %(date)s, %(start_local)s, %(sport)s,
    %(title)s, %(description)s, %(structure)s, %(planned_tss)s, %(planned_if)s,
    %(planned_moving_s)s, %(raw)s)
ON CONFLICT (athlete_id, source, external_id) DO UPDATE SET
    date = EXCLUDED.date, start_local = EXCLUDED.start_local, sport = EXCLUDED.sport,
    title = EXCLUDED.title, description = EXCLUDED.description,
    structure = EXCLUDED.structure, planned_tss = EXCLUDED.planned_tss,
    planned_if = EXCLUDED.planned_if, planned_moving_s = EXCLUDED.planned_moving_s,
    raw = EXCLUDED.raw
RETURNING id
"""

_PLANNED_COLUMNS = (
    "id, date, start_local, sport, title, description, planned_tss, planned_if, paired_activity_id"
)


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _day_end(day: date) -> datetime:
    return datetime.combine(day, time.max)


class PgPlanStore:
    def __init__(self, conn: db.Conn) -> None:
        self.conn = conn

    def upsert_planned(self, row: PlannedRow) -> int:
        params = {
            **row,
            "structure": None if row["structure"] is None else Jsonb(row["structure"]),
            "raw": Jsonb(row["raw"]),
        }
        found = self.conn.execute(_UPSERT_PLANNED, params).fetchone()
        if found is None:
            raise RuntimeError("planned session upsert returned no row")
        pid: int = found[0]
        return pid

    def plan_refs(self, athlete_id: str, oldest: date, newest: date) -> list[PlanRef]:
        rows = self.conn.execute(
            "SELECT id, date, sport, start_local FROM planned_sessions "
            "WHERE athlete_id = %s AND date BETWEEN %s AND %s ORDER BY id",
            (athlete_id, oldest, newest),
        ).fetchall()
        return [PlanRef(r[0], r[1], r[2], r[3]) for r in rows]

    def activity_refs(self, athlete_id: str, oldest: date, newest: date) -> list[ActivityRef]:
        rows = self.conn.execute(
            "SELECT id, sport, start_local FROM activities "
            "WHERE athlete_id = %s AND start_local BETWEEN %s AND %s ORDER BY start_local",
            (athlete_id, datetime.combine(oldest, time.min), _day_end(newest)),
        ).fetchall()
        return [ActivityRef(r[0], r[1], r[2]) for r in rows]

    def record_pairing(self, athlete_id: str, oldest: date, newest: date, p: Pairing) -> None:
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE planned_sessions SET paired_activity_id = NULL "
                "WHERE athlete_id = %s AND date BETWEEN %s AND %s",
                (athlete_id, oldest, newest),
            )
            for pid, aid in p.paired.items():
                self.conn.execute(
                    "UPDATE planned_sessions SET paired_activity_id = %s WHERE id = %s",
                    (aid, pid),
                )

    def planned_on(self, athlete_id: str, day: date) -> list[PlannedSession]:
        rows = self.conn.execute(
            f"SELECT {_PLANNED_COLUMNS} FROM planned_sessions "
            "WHERE athlete_id = %s AND date = %s ORDER BY id",
            (athlete_id, day),
        ).fetchall()
        return [
            PlannedSession(
                id=r[0],
                date=r[1],
                start_local=r[2],
                sport=r[3],
                title=r[4],
                description=r[5],
                planned_tss=_float(r[6]),
                planned_if=_float(r[7]),
                paired_activity_id=r[8],
            )
            for r in rows
        ]

    def executed(self, activity_id: int) -> ExecutedSession | None:
        r = self.conn.execute(
            'SELECT id, sport, start_local, np_w, avg_hr, max_hr, "if" FROM activities '
            "WHERE id = %s",
            (activity_id,),
        ).fetchone()
        if r is None:
            return None
        work = self.conn.execute(
            "SELECT dur_s, avg_hr FROM activity_intervals "
            "WHERE activity_id = %s AND upper(kind) = %s ORDER BY idx",
            (activity_id, WORK_KIND),
        ).fetchall()
        return ExecutedSession(
            id=r[0],
            sport=r[1],
            start_local=r[2],
            np_w=_float(r[3]),
            avg_hr=_float(r[4]),
            max_hr=_float(r[5]),
            intensity_factor=_float(r[6]),
            work_intervals=tuple(WorkInterval(_float(w[0]), _float(w[1])) for w in work),
        )
