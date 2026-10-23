"""Ingest intervals.icu activities, intervals, streams and wellness into Postgres.

Idempotent: activities upsert on (athlete_id, source, external_id); streams and
intervals are replaced per activity; wellness upserts on (athlete_id, date).

Usage: python -m domestique.ingest.icu --from 2026-09-01 [--to 2026-09-30]

Field names below follow the intervals.icu API as seen in the activities and
wellness endpoints; streams and per-interval L/R names are best-effort (see
STREAM_TYPES) and missing fields simply stay NULL.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, TypedDict

import psycopg

from domestique import db
from domestique.ingest import icu_client
from domestique.ingest.icu_client import IcuPayload
from domestique.metrics import (
    Interval,
    Sample,
    decoupling_pct,
    efficiency_factor,
    interval_lr_balance,
    lr_balance,
)

SOURCE = "intervals.icu"
STREAM_TYPES = "time,watts,heartrate,cadence,temp,left_right_balance"


# --- row shapes -------------------------------------------------------------

# "if" is a keyword, so the activity row needs the functional TypedDict syntax.
ActivityRow = TypedDict(
    "ActivityRow",
    {
        "athlete_id": str,
        "source": str,
        "external_id": str,
        "start_local": datetime | None,
        "start_utc": datetime | None,
        "sport": str | None,
        "name": str | None,
        "moving_s": int | None,
        "avg_w": float | None,
        "np_w": float | None,
        "avg_hr": float | None,
        "max_hr": float | None,
        "avg_cad": float | None,
        "ftp_at_ride": float | None,
        "load": float | None,
        "if": float | None,
        "ef": float | None,
        "decoupling": float | None,
        "lr_balance": float | None,
        "raw": str,
    },
)


class IntervalRow(TypedDict):
    idx: int
    kind: str | None
    start_s: float | None
    dur_s: float | None
    avg_w: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_cad: float | None
    lr_balance: float | None


class WellnessRow(TypedDict):
    athlete_id: str
    date: date
    hrv: float | None
    rhr: float | None
    sleep_s: float | None
    sleep_score: float | None
    weight: float | None
    ctl: float | None
    atl: float | None
    source: str
    raw: str


# --- pure mapping: API payloads -> row dicts -------------------------------


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def samples_from_streams(streams: list[IcuPayload]) -> list[Sample]:
    """Zip icu stream arrays into sample dicts (t_s, watts, hr, cadence, lr, temp)."""
    by_type = {s["type"]: s["data"] for s in streams if s.get("data") is not None}
    n = max((len(v) for v in by_type.values()), default=0)
    time = by_type.get("time") or list(range(n))
    lr = by_type.get("left_right_balance") or by_type.get("lr") or []

    def at(arr: Sequence[Any], i: int) -> Any:
        return arr[i] if i < len(arr) else None

    return [
        {
            "t_s": time[i],
            "watts": at(by_type.get("watts", []), i),
            "hr": at(by_type.get("heartrate", []), i),
            "cadence": at(by_type.get("cadence", []), i),
            "lr": at(lr, i),
            "temp": at(by_type.get("temp", []), i),
        }
        for i in range(n)
    ]


def map_activity(
    a: IcuPayload, athlete_id: str, samples: list[Sample] | None = None
) -> ActivityRow:
    """Activity row. Our own EF/decoupling/L-R from streams win over icu's when streams exist."""
    start_local = _dt(a["start_date_local"])
    intensity = a.get("icu_intensity")
    row: ActivityRow = {
        "athlete_id": athlete_id,
        "source": SOURCE,
        "external_id": str(a["id"]),
        "start_local": start_local,
        "start_utc": _dt(a.get("start_date")),
        "sport": a.get("type"),
        "name": a.get("name"),
        "moving_s": a.get("moving_time"),
        "avg_w": a.get("icu_average_watts") or a.get("average_watts"),
        "np_w": a.get("icu_weighted_avg_watts"),
        "avg_hr": a.get("average_heartrate"),
        "max_hr": a.get("max_heartrate"),
        "avg_cad": a.get("average_cadence"),
        "ftp_at_ride": a.get("icu_ftp"),
        "load": a.get("icu_training_load"),
        "if": intensity / 100 if intensity is not None else None,  # icu reports percent
        "ef": a.get("icu_efficiency_factor"),
        "decoupling": a.get("decoupling"),
        "lr_balance": a.get("avg_lr_balance"),
        "raw": json.dumps(a),
    }
    if samples:
        row["ef"] = efficiency_factor(samples) or row["ef"]
        dec = decoupling_pct(samples)
        row["decoupling"] = dec if dec is not None else row["decoupling"]
        lr = lr_balance(samples)
        row["lr_balance"] = lr if lr is not None else row["lr_balance"]
    return row


def map_intervals(
    payload: IcuPayload | list[IcuPayload], samples: list[Sample] | None = None
) -> list[IntervalRow]:
    items = payload.get("icu_intervals", []) if isinstance(payload, dict) else payload
    rows: list[IntervalRow] = []
    for idx, iv in enumerate(items):
        start = iv.get("start_time", iv.get("start_index"))
        dur = iv.get("elapsed_time", iv.get("moving_time"))
        rows.append(
            {
                "idx": idx,
                "kind": iv.get("type"),
                "start_s": start,
                "dur_s": dur,
                "avg_w": iv.get("average_watts"),
                "avg_hr": iv.get("average_heartrate"),
                "max_hr": iv.get("max_heartrate"),
                "avg_cad": iv.get("average_cadence"),
                "lr_balance": iv.get("avg_lr_balance"),
            }
        )
    if samples:
        _apply_interval_balance(rows, samples)
    return rows


def _span(row: IntervalRow) -> Interval | None:
    """The interval's position in the ride, or None when the payload did not locate it."""
    start, dur = row["start_s"], row["dur_s"]
    if start is None or dur is None:
        return None
    return {"start_s": start, "dur_s": dur}


def _apply_interval_balance(rows: list[IntervalRow], samples: list[Sample]) -> None:
    """Overwrite each locatable interval's L/R balance with the one computed from streams."""
    located = [(r, span) for r in rows if (span := _span(r)) is not None]
    balances = interval_lr_balance(samples, [span for _, span in located])
    for (row, _), lr in zip(located, balances, strict=True):
        if lr is not None:
            row["lr_balance"] = lr


def map_wellness(w: IcuPayload, athlete_id: str) -> WellnessRow:
    return {
        "athlete_id": athlete_id,
        "date": date.fromisoformat(str(w["id"])[:10]),
        "hrv": w.get("hrv"),
        "rhr": w.get("restingHR"),
        "sleep_s": w.get("sleepSecs"),
        "sleep_score": w.get("sleepScore"),
        "weight": w.get("weight"),
        "ctl": w.get("ctl"),
        "atl": w.get("atl"),
        "source": SOURCE,
        "raw": json.dumps(w),
    }


# --- database writes -------------------------------------------------------


def _upsert(
    conn: db.Conn, table: str, row: Mapping[str, Any], conflict: Sequence[str]
) -> psycopg.Cursor[tuple[Any, ...]]:
    cols = list(row)
    quoted = ", ".join(f'"{c}"' for c in cols)
    marks = ", ".join(f"%({c})s" for c in cols)
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in conflict)
    key = ", ".join(conflict)
    return conn.execute(
        f"INSERT INTO {table} ({quoted}) VALUES ({marks}) "
        f"ON CONFLICT ({key}) DO UPDATE SET {updates} RETURNING *",
        row,
    )


def _upsert_activity(conn: db.Conn, row: ActivityRow) -> int:
    cur = _upsert(conn, "activities", row, ["athlete_id", "source", "external_id"])
    created = cur.fetchone()
    if created is None:
        raise RuntimeError("activity upsert returned no row")
    activity_id: int = created[0]
    return activity_id


def _replace_intervals(conn: db.Conn, activity_id: int, intervals: Sequence[IntervalRow]) -> None:
    conn.execute("DELETE FROM activity_intervals WHERE activity_id = %s", (activity_id,))
    for iv in intervals:
        _upsert(
            conn,
            "activity_intervals",
            {"activity_id": activity_id, **iv},
            ["activity_id", "idx"],
        )


def _replace_streams(conn: db.Conn, activity_id: int, samples: Sequence[Sample]) -> None:
    conn.execute("DELETE FROM activity_streams WHERE activity_id = %s", (activity_id,))
    if not samples:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO activity_streams (activity_id, t_s, watts, hr, cadence, lr, temp) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [
                (
                    activity_id,
                    s["t_s"],
                    s["watts"],
                    s["hr"],
                    s["cadence"],
                    s["lr"],
                    s["temp"],
                )
                for s in samples
            ],
        )


def _record_ftp_change(conn: db.Conn, row: ActivityRow) -> None:
    """Append to ftp_history when the ride's FTP differs from the one in force that day."""
    ftp = row["ftp_at_ride"]
    if not ftp:
        return
    start_local = row["start_local"]
    if start_local is None:
        raise ValueError("activity has an FTP but no local start time")
    on = start_local.date()
    prev = conn.execute(
        "SELECT ftp_w FROM ftp_history WHERE athlete_id = %s AND valid_from <= %s "
        "ORDER BY valid_from DESC LIMIT 1",
        (row["athlete_id"], on),
    ).fetchone()
    if prev is None or float(prev[0]) != float(ftp):
        conn.execute(
            "INSERT INTO ftp_history (athlete_id, valid_from, ftp_w, source) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (athlete_id, valid_from) DO NOTHING",
            (row["athlete_id"], on, ftp, SOURCE),
        )


def store_activity(
    conn: db.Conn,
    row: ActivityRow,
    intervals: Sequence[IntervalRow],
    samples: Sequence[Sample],
) -> int:
    with conn.transaction():
        activity_id = _upsert_activity(conn, row)
        _replace_intervals(conn, activity_id, intervals)
        _replace_streams(conn, activity_id, samples)
        _record_ftp_change(conn, row)
    return activity_id


def store_wellness(conn: db.Conn, row: WellnessRow) -> None:
    _upsert(conn, "wellness", row, ["athlete_id", "date"])


# --- orchestration ---------------------------------------------------------


def ingest(
    conn: db.Conn,
    client: icu_client.IcuClient,
    oldest: date,
    newest: date,
    with_streams: bool = True,
) -> dict[str, int]:
    athlete_id = client.athlete_id
    activities = sorted(
        client.activities(oldest.isoformat(), newest.isoformat()),
        key=lambda a: a["start_date_local"],
    )
    n_act = 0
    for a in activities:
        samples = (
            samples_from_streams(client.streams(a["id"], STREAM_TYPES)) if with_streams else []
        )
        row = map_activity(a, athlete_id, samples)
        intervals = map_intervals(client.intervals(a["id"]), samples)
        store_activity(conn, row, intervals, samples)
        n_act += 1
    n_well = 0
    for w in client.wellness(oldest.isoformat(), newest.isoformat()):
        store_wellness(conn, map_wellness(w, athlete_id))
        n_well += 1
    conn.commit()
    return {"activities": n_act, "wellness": n_well}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Ingest intervals.icu into the data plane.")
    p.add_argument("--from", dest="oldest", required=True, type=date.fromisoformat)
    p.add_argument("--to", dest="newest", type=date.fromisoformat, default=datetime.now(UTC).date())
    p.add_argument("--no-streams", action="store_true", help="skip per-second streams")
    args = p.parse_args(argv)

    with db.connect() as conn:
        applied = db.migrate(conn)
        if applied:
            print("applied migrations:", ", ".join(applied))
        client = icu_client.IcuClient(icu_client.get_athlete_id(), icu_client.make_client())
        counts = ingest(conn, client, args.oldest, args.newest, with_streams=not args.no_streams)
    print(f"ingested {counts['activities']} activities, {counts['wellness']} wellness days")


if __name__ == "__main__":
    main()
