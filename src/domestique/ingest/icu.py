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
from datetime import UTC, date, datetime

import psycopg

from domestique import db
from domestique.ingest import icu_client
from domestique.metrics import decoupling_pct, efficiency_factor, interval_lr_balance, lr_balance

SOURCE = "intervals.icu"
STREAM_TYPES = "time,watts,heartrate,cadence,temp,left_right_balance"


# --- pure mapping: API payloads -> row dicts -------------------------------


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def samples_from_streams(streams: list[dict]) -> list[dict]:
    """Zip icu stream arrays into sample dicts (t_s, watts, hr, cadence, lr, temp)."""
    by_type = {s["type"]: s["data"] for s in streams if s.get("data") is not None}
    n = max((len(v) for v in by_type.values()), default=0)
    time = by_type.get("time") or list(range(n))
    lr = by_type.get("left_right_balance") or by_type.get("lr") or []

    def at(arr, i):
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


def map_activity(a: dict, athlete_id: str, samples: list[dict] | None = None) -> dict:
    """Activity row. Our own EF/decoupling/L-R from streams win over icu's when streams exist."""
    start_local = _dt(a["start_date_local"])
    intensity = a.get("icu_intensity")
    row = {
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


def map_intervals(payload: dict | list, samples: list[dict] | None = None) -> list[dict]:
    items = payload.get("icu_intervals", []) if isinstance(payload, dict) else payload
    rows = []
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
        located = [r for r in rows if r["start_s"] is not None and r["dur_s"] is not None]
        for r, lr in zip(located, interval_lr_balance(samples, located), strict=True):
            if lr is not None:
                r["lr_balance"] = lr
    return rows


def map_wellness(w: dict, athlete_id: str) -> dict:
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


def _upsert(conn, table: str, row: dict, conflict: list[str]) -> psycopg.Cursor:
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


def store_activity(
    conn: psycopg.Connection, row: dict, intervals: list[dict], samples: list[dict]
) -> int:
    with conn.transaction():
        activity_id = _upsert(conn, "activities", row, ["athlete_id", "source", "external_id"])
        activity_id = activity_id.fetchone()[0]
        conn.execute("DELETE FROM activity_intervals WHERE activity_id = %s", (activity_id,))
        for iv in intervals:
            _upsert(
                conn,
                "activity_intervals",
                {"activity_id": activity_id, **iv},
                ["activity_id", "idx"],
            )
        conn.execute("DELETE FROM activity_streams WHERE activity_id = %s", (activity_id,))
        if samples:
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
        ftp = row.get("ftp_at_ride")
        if ftp:
            on = row["start_local"].date()
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
    return activity_id


def store_wellness(conn: psycopg.Connection, row: dict) -> None:
    _upsert(conn, "wellness", row, ["athlete_id", "date"])


# --- orchestration ---------------------------------------------------------


def ingest(
    conn: psycopg.Connection,
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
