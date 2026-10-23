"""Ingest planned workouts from the intervals.icu events API and pair them.

Planned workouts are calendar events with ``category == "WORKOUT"``; notes,
races and other categories are skipped. Idempotent: rows upsert on
(athlete_id, source, external_id) where external_id is the event id, and the
pairing for the ingested date range is recomputed on every run. The event
payload is kept whole in ``raw``; only fields the Event schema documents are
mapped and every one of them is treated as optional except ``id`` and
``start_date_local``. Nothing is ever written back to the platform.

Usage: python -m domestique.ingest.icu_plan --from 2026-09-01 [--to 2026-09-30]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Protocol

import httpx

from domestique import db
from domestique.ingest import icu_client
from domestique.ingest.icu_client import IcuPayload
from domestique.ingest.pairing import Pairing, pair
from domestique.ingest.plan_store import PgPlanStore, PlannedRow, PlanStore

SOURCE = "intervals.icu"
WORKOUT = "WORKOUT"


class EventsSource(Protocol):
    athlete_id: str

    def events(self, oldest: str, newest: str) -> list[IcuPayload]: ...


class IcuEvents:
    """The events endpoint, over the same authenticated HTTP client as the activity ingest."""

    def __init__(self, athlete_id: str, http: httpx.Client) -> None:
        self.athlete_id = athlete_id
        self.http = http

    def events(self, oldest: str, newest: str) -> list[IcuPayload]:
        r = self.http.get(
            f"/api/v1/athlete/{self.athlete_id}/events",
            params={"oldest": oldest, "newest": newest},
        )
        r.raise_for_status()
        rows: list[IcuPayload] = r.json()
        return rows


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def map_event(e: IcuPayload, athlete_id: str) -> PlannedRow | None:
    """A planned-session row, or None for events that are not planned workouts."""
    if e.get("category") != WORKOUT:
        return None
    start = datetime.fromisoformat(str(e["start_date_local"]))
    intensity = _number(e.get("icu_intensity"))
    moving = _number(e.get("moving_time"))
    return {
        "athlete_id": athlete_id,
        "source": SOURCE,
        "external_id": str(e["id"]),
        "date": start.date(),
        "start_local": start,
        "sport": e.get("type"),
        "title": e.get("name"),
        "description": e.get("description"),
        "structure": e.get("workout_doc"),
        "planned_tss": _number(e.get("icu_training_load")),
        "planned_if": intensity / 100 if intensity is not None else None,  # icu reports percent
        "planned_moving_s": int(moving) if moving is not None else None,
        "raw": e,
    }


def map_events(events: Iterable[IcuPayload], athlete_id: str) -> list[PlannedRow]:
    return [row for e in events if (row := map_event(e, athlete_id)) is not None]


def pair_range(store: PlanStore, athlete_id: str, oldest: date, newest: date) -> Pairing:
    """Recompute and record the pairing for every planned session in the range."""
    result = pair(
        store.plan_refs(athlete_id, oldest, newest),
        store.activity_refs(athlete_id, oldest, newest),
    )
    store.record_pairing(athlete_id, oldest, newest, result)
    return result


def ingest_planned(
    store: PlanStore, source: EventsSource, oldest: date, newest: date
) -> dict[str, int]:
    rows = map_events(source.events(oldest.isoformat(), newest.isoformat()), source.athlete_id)
    for row in rows:
        store.upsert_planned(row)
    result = pair_range(store, source.athlete_id, oldest, newest)
    return {"planned": len(rows), "paired": len(result.paired), "missed": len(result.missed)}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Ingest intervals.icu planned workouts.")
    p.add_argument("--from", dest="oldest", required=True, type=date.fromisoformat)
    p.add_argument("--to", dest="newest", type=date.fromisoformat, default=datetime.now(UTC).date())
    args = p.parse_args(argv)
    with db.connect() as conn:
        db.migrate(conn)
        source = IcuEvents(icu_client.get_athlete_id(), icu_client.make_client())
        counts = ingest_planned(PgPlanStore(conn), source, args.oldest, args.newest)
        conn.commit()
    sys.stdout.write(
        f"planned {counts['planned']}, paired {counts['paired']}, missed {counts['missed']}\n"
    )


if __name__ == "__main__":
    main()
