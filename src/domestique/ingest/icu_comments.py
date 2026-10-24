"""Ingest intervals.icu activity comments into the subjective table.

Each upstream comment becomes one ``subjective`` row keyed by
``(athlete_id, source, external_id)``, so re-running updates edited comments
instead of duplicating them. Pin indices (``start_index``/``end_index``) are
kept so a comment can be joined to the interval covering that stretch.

The ``#fuel`` tag (see ``fuel_tag``) in the latest comment that carries one
becomes the ride's row in ``activity_intake``; its carbohydrate replaces the
platform's ``carbs_ingested`` while the platform value is retained for audit.
Deleted comments and the system's own comments never contribute intake.

Usage: python -m domestique.ingest.icu_comments --from 2026-09-01 [--to 2026-09-30]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypedDict

import httpx

from domestique import db
from domestique.ingest import fuel_tag, icu_client
from domestique.ingest.icu_client import IcuPayload
from domestique.ingest.settings import SOURCE, cli_settings
from domestique.output.comments import is_system_comment


class CommentsApi:
    """The two activity-message endpoints: read comments, post one."""

    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def messages(self, activity_id: str) -> list[IcuPayload]:
        r = self.http.get(f"/api/v1/activity/{activity_id}/messages")
        r.raise_for_status()
        rows: list[IcuPayload] = r.json()
        return rows

    def post_message(self, activity_id: str, body: dict[str, object]) -> IcuPayload:
        r = self.http.post(f"/api/v1/activity/{activity_id}/messages", json=body)
        r.raise_for_status()
        created: IcuPayload = r.json()
        return created


class CommentRow(TypedDict):
    athlete_id: str
    ts: datetime
    activity_id: int
    answer: str
    tags: list[str]
    source: str
    external_id: str
    author_id: str | None
    author_name: str | None
    start_index: int | None
    end_index: int | None
    deleted: bool
    is_system: bool


@dataclass(frozen=True)
class Intake:
    """A ride's reconciled intake. The tag wins; the platform carbohydrate is kept."""

    fluid_ml: float | None
    carbs_g: float | None
    kcal: float | None
    platform_carbs_g: float | None
    carbs_differ: bool
    comment_external_id: str


# --- pure mapping ------------------------------------------------------------


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def map_comment(m: IcuPayload, athlete_id: str, activity_id: int) -> CommentRow:
    """One upstream message as a subjective row. The text is stored unmodified."""
    content = str(m.get("content") or "")
    system = is_system_comment(content)
    tags = ["comment"]
    if system:
        tags.append("system")
    elif fuel_tag.parse(content) is not None:
        tags.append("fuel")
    return {
        "athlete_id": athlete_id,
        "ts": _ts(str(m["created"])),
        "activity_id": activity_id,
        "answer": content,
        "tags": tags,
        "source": SOURCE,
        "external_id": str(m["id"]),
        "author_id": _opt_str(m.get("athlete_id")),
        "author_name": _opt_str(m.get("name")),
        "start_index": m.get("start_index"),
        "end_index": m.get("end_index"),
        "deleted": bool(m.get("deleted")),
        "is_system": system,
    }


def _order(row: CommentRow) -> tuple[datetime, int, str]:
    ext = row["external_id"]
    return (row["ts"], int(ext) if ext.isdigit() else 0, ext)


def latest_tag(rows: Iterable[CommentRow]) -> tuple[fuel_tag.Tag, str] | None:
    """The tag in the most recent live athlete comment carrying one, with that comment's id."""
    live = sorted((r for r in rows if not r["deleted"] and not r["is_system"]), key=_order)
    for row in reversed(live):
        tag = fuel_tag.parse(row["answer"])
        if tag is not None:
            return tag, row["external_id"]
    return None


def reconcile(tag: fuel_tag.Tag, comment_id: str, platform_carbs_g: float | None) -> Intake:
    """Tag values win; the platform's carbohydrate is retained, and a disagreement flagged."""
    carbs = tag.carbs_g if tag.carbs_g is not None else platform_carbs_g
    differ = (
        tag.carbs_g is not None
        and platform_carbs_g is not None
        and float(platform_carbs_g) != tag.carbs_g
    )
    return Intake(
        fluid_ml=tag.fluid_ml,
        carbs_g=carbs,
        kcal=tag.kcal,
        platform_carbs_g=platform_carbs_g,
        carbs_differ=differ,
        comment_external_id=comment_id,
    )


# --- database writes ---------------------------------------------------------

_COMMENT_COLUMNS = tuple(CommentRow.__annotations__)
_CONFLICT = ("athlete_id", "source", "external_id")


def store_comment(conn: db.Conn, row: CommentRow) -> None:
    cols = ", ".join(_COMMENT_COLUMNS)
    marks = ", ".join(f"%({c})s" for c in _COMMENT_COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COMMENT_COLUMNS if c not in _CONFLICT)
    conn.execute(
        f"INSERT INTO subjective ({cols}) VALUES ({marks}) "
        f"ON CONFLICT ({', '.join(_CONFLICT)}) DO UPDATE SET {updates}",
        row,
    )


def store_intake(conn: db.Conn, activity_id: int, intake: Intake | None) -> None:
    """Write the ride's intake, or clear it when no tag remains upstream."""
    if intake is None:
        conn.execute("DELETE FROM activity_intake WHERE activity_id = %s", (activity_id,))
        return
    conn.execute(
        "INSERT INTO activity_intake (activity_id, fluid_ml, carbs_g, kcal, platform_carbs_g, "
        "carbs_differ, comment_external_id) VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (activity_id) DO UPDATE SET fluid_ml = EXCLUDED.fluid_ml, "
        "carbs_g = EXCLUDED.carbs_g, kcal = EXCLUDED.kcal, "
        "platform_carbs_g = EXCLUDED.platform_carbs_g, carbs_differ = EXCLUDED.carbs_differ, "
        "comment_external_id = EXCLUDED.comment_external_id, updated_at = now()",
        (
            activity_id,
            intake.fluid_ml,
            intake.carbs_g,
            intake.kcal,
            intake.platform_carbs_g,
            intake.carbs_differ,
            intake.comment_external_id,
        ),
    )


# --- orchestration -----------------------------------------------------------


@dataclass(frozen=True)
class StoredActivity:
    """What comment ingestion needs to know about an activity already in the data plane."""

    id: int
    external_id: str
    platform_carbs_g: float | None


def activities_between(
    conn: db.Conn, athlete_id: str, oldest: date, newest: date
) -> list[StoredActivity]:
    rows = conn.execute(
        "SELECT id, external_id, carbs_ingested_g FROM activities "
        "WHERE athlete_id = %s AND source = %s AND start_local >= %s AND start_local < %s "
        "ORDER BY start_local",
        (athlete_id, SOURCE, oldest, newest + timedelta(days=1)),
    ).fetchall()
    return [
        StoredActivity(int(r[0]), str(r[1]), None if r[2] is None else float(r[2])) for r in rows
    ]


def ingest_activity(
    conn: db.Conn, api: CommentsApi, athlete_id: str, activity: StoredActivity
) -> int:
    """Store every comment on one activity and its reconciled intake; returns the comment count."""
    rows = [map_comment(m, athlete_id, activity.id) for m in api.messages(activity.external_id)]
    found = latest_tag(rows)
    intake = reconcile(*found, activity.platform_carbs_g) if found else None
    with conn.transaction():
        for row in rows:
            store_comment(conn, row)
        store_intake(conn, activity.id, intake)
    return len(rows)


def ingest(
    conn: db.Conn, api: CommentsApi, athlete_id: str, oldest: date, newest: date
) -> dict[str, int]:
    """Comments for every stored activity in the date range (one request per activity)."""
    activities: Sequence[StoredActivity] = activities_between(conn, athlete_id, oldest, newest)
    n_comments = sum(ingest_activity(conn, api, athlete_id, a) for a in activities)
    conn.commit()
    return {"activities": len(activities), "comments": n_comments}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Ingest intervals.icu activity comments.")
    p.add_argument("--from", dest="oldest", required=True, type=date.fromisoformat)
    p.add_argument("--to", dest="newest", type=date.fromisoformat, default=datetime.now(UTC).date())
    args = p.parse_args(argv)

    athlete_id, dsn = cli_settings()
    with db.connect(dsn) as conn:
        db.migrate(conn)
        api = CommentsApi(icu_client.make_client())
        counts = ingest(conn, api, athlete_id, args.oldest, args.newest)
    sys.stdout.write(
        f"ingested {counts['comments']} comments on {counts['activities']} activities\n"
    )


if __name__ == "__main__":
    main()
