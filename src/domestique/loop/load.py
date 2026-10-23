"""Database loaders for the loop. Small, read-only, and the only place the loop queries.

``load_history`` gives the predictor what precedes a planned session;
``load_actuals`` gives the scorer what happened in it and the next morning.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any

from domestique import db
from domestique.ingest.pairing import sport_family
from domestique.ingest.plan_store import PlannedSession
from domestique.loop.model import BASELINE_NIGHTS, Actuals, History, RideSamples
from domestique.metrics.types import Sample

LOOKBACK_DAYS = 90
MAX_RIDES = 10  # earlier rides whose streams are loaded for the watts-at-HR base
_CANDIDATES = 50  # recent activities scanned for a sport-family match
SECONDS_PER_HOUR = 3600.0


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def load_samples(conn: db.Conn, activity_id: int) -> list[Sample]:
    rows = conn.execute(
        "SELECT t_s, watts, hr FROM activity_streams WHERE activity_id = %s ORDER BY t_s",
        (activity_id,),
    ).fetchall()
    return [{"t_s": float(r[0]), "watts": _num(r[1]), "hr": _num(r[2])} for r in rows]


def _earlier_ride_ids(conn: db.Conn, athlete_id: str, session: PlannedSession) -> list[int]:
    start = datetime.combine(session.date, time.min)
    rows = conn.execute(
        "SELECT id, sport FROM activities WHERE athlete_id = %s "
        "AND start_local < %s AND start_local >= %s ORDER BY start_local DESC LIMIT %s",
        (athlete_id, start, start - timedelta(days=LOOKBACK_DAYS), _CANDIDATES),
    ).fetchall()
    family = sport_family(session.sport)
    ids = [r[0] for r in rows if family is None or sport_family(r[1]) == family]
    return ids[:MAX_RIDES]


def _nights(
    conn: db.Conn, athlete_id: str, day: date
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    rows = conn.execute(
        "SELECT hrv, sleep_s FROM wellness WHERE athlete_id = %s "
        "AND date <= %s AND date > %s ORDER BY date DESC",
        (athlete_id, day, day - timedelta(days=BASELINE_NIGHTS)),
    ).fetchall()
    hrv = tuple(float(r[0]) for r in rows if r[0] is not None)
    sleep = tuple(float(r[1]) / SECONDS_PER_HOUR for r in rows if r[1] is not None)
    return hrv, sleep


def load_history(
    conn: db.Conn,
    athlete_id: str,
    session: PlannedSession,
    hr_max: float | None,
    baselines: Mapping[str, float],
) -> History:
    """Everything before the session's day: earlier rides of its sport family and recent nights."""
    rides = tuple(
        RideSamples(aid, load_samples(conn, aid))
        for aid in _earlier_ride_ids(conn, athlete_id, session)
    )
    hrv, sleep = _nights(conn, athlete_id, session.date)
    return History(hr_max=hr_max, baselines=dict(baselines), rides=rides, hrv=hrv, sleep_h=sleep)


def _next_morning(conn: db.Conn, athlete_id: str, day: date) -> tuple[float | None, float | None]:
    row = conn.execute(
        "SELECT hrv, sleep_s FROM wellness WHERE athlete_id = %s AND date = %s",
        (athlete_id, day + timedelta(days=1)),
    ).fetchone()
    if row is None:
        return None, None
    sleep = None if row[1] is None else float(row[1]) / SECONDS_PER_HOUR
    return _num(row[0]), sleep


def load_actuals(conn: db.Conn, athlete_id: str, session: PlannedSession) -> Actuals:
    """The paired ride (if any) and the wellness of the morning after the session's day."""
    hrv, sleep = _next_morning(conn, athlete_id, session.date)
    aid = session.paired_activity_id
    if aid is None:
        return Actuals(None, hrv_next_morning=hrv, sleep_hours=sleep)
    row = conn.execute("SELECT max_hr FROM activities WHERE id = %s", (aid,)).fetchone()
    return Actuals(
        activity_id=aid,
        samples=load_samples(conn, aid),
        max_hr=_num(row[0]) if row else None,
        hrv_next_morning=hrv,
        sleep_hours=sleep,
    )
