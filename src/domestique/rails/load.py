"""Read one day's ``DayData`` from the data-plane tables.

- subjective tags: ``subjective.tags`` of every entry whose timestamp falls on
  the day in the athlete's timezone
- HRV: ``wellness.hrv`` on the day
- CTL change over 7 days: ``wellness.ctl`` on the day minus seven days earlier;
  None when either row or value is missing
- context kinds: ``context.kind`` on the day
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from domestique import db
from domestique.rails.registry import DayData

RAMP_WINDOW_DAYS = 7


def _subjective_tags(conn: db.Conn, athlete_id: str, day: date, timezone: str) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT DISTINCT tag FROM subjective, unnest(tags) AS tag "
        "WHERE athlete_id = %s AND (ts AT TIME ZONE %s)::date = %s ORDER BY tag",
        (athlete_id, timezone, day),
    ).fetchall()
    return tuple(str(r[0]) for r in rows)


def _num(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _wellness(conn: db.Conn, athlete_id: str, day: date) -> tuple[float | None, float | None]:
    """``(hrv, ctl)`` on the day; both None without a wellness row."""
    row = conn.execute(
        "SELECT hrv, ctl FROM wellness WHERE athlete_id = %s AND date = %s",
        (athlete_id, day),
    ).fetchone()
    if row is None:
        return None, None
    return _num(row[0]), _num(row[1])


def _ctl_delta(conn: db.Conn, athlete_id: str, day: date, today: float | None) -> float | None:
    _, before = _wellness(conn, athlete_id, day - timedelta(days=RAMP_WINDOW_DAYS))
    if today is None or before is None:
        return None
    return today - before


def _context_kinds(conn: db.Conn, athlete_id: str, day: date) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT kind FROM context WHERE athlete_id = %s AND date = %s ORDER BY kind",
        (athlete_id, day),
    ).fetchall()
    return tuple(str(r[0]) for r in rows)


def load_day(conn: db.Conn, athlete_id: str, day: date, timezone: str = "UTC") -> DayData:
    """The rails' view of ``day`` for ``athlete_id``; absent rows leave fields at defaults."""
    hrv, ctl = _wellness(conn, athlete_id, day)
    return DayData(
        date=day,
        subjective_tags=_subjective_tags(conn, athlete_id, day, timezone),
        hrv=hrv,
        ctl_delta_7d=_ctl_delta(conn, athlete_id, day, ctl),
        context_kinds=_context_kinds(conn, athlete_id, day),
    )
