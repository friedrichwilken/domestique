"""Integration: set DOMESTIQUE_TEST_DSN to a scratch TimescaleDB database."""

import json
import os
import uuid
from datetime import date
from pathlib import Path

import pytest

from domestique import db
from domestique.ingest import icu, icu_comments

pytestmark = pytest.mark.skipif(
    not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN"
)

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "evals" / "fixtures" / "icu_nutrition_comments.json").read_text()
)


class FakeIcu:
    def __init__(self, messages):
        self.by_activity = {"i2002": messages}

    def messages(self, activity_id):
        return [dict(m) for m in self.by_activity.get(activity_id, [])]


@pytest.fixture
def conn():
    with db.connect(os.environ["DOMESTIQUE_TEST_DSN"]) as c:
        db.migrate(c)
        yield c


@pytest.fixture
def athlete():
    return f"iT{uuid.uuid4().hex[:8]}"


def store(conn, athlete, key):
    return icu.store_activity(conn, icu.map_activity(FIXTURE[key], athlete), [], [])


def run(conn, athlete, messages):
    return icu_comments.ingest(
        conn, FakeIcu(messages), athlete, date(2026, 9, 1), date(2026, 9, 30)
    )


def test_ride_without_logged_intake_stores_null(conn, athlete):
    aid = store(conn, athlete, "activity_no_intake")
    kcal, used, ingested = conn.execute(
        "SELECT kcal, carbs_used_g, carbs_ingested_g FROM activities WHERE id = %s", (aid,)
    ).fetchone()
    assert (kcal, used, ingested) == (3100, 520, None)
    icu.store_wellness(conn, icu.map_wellness(FIXTURE["wellness"], athlete))
    w = conn.execute(
        "SELECT kcal_consumed, carbs_g, protein_g, fat_g, hydration_ml, hydration "
        "FROM wellness WHERE athlete_id = %s",
        (athlete,),
    ).fetchone()
    assert w == (3600, 520, 140, 90, 3200, 3)


def test_pinned_comment_and_edit_are_idempotent(conn, athlete):
    aid = store(conn, athlete, "activity_platform_carbs")
    messages = [dict(m) for m in FIXTURE["messages"]]
    assert run(conn, athlete, messages) == {"activities": 1, "comments": 2}
    messages[1]["content"] = "Legs heavy on this climb (edited)"
    run(conn, athlete, messages)
    rows = conn.execute(
        "SELECT external_id, answer, start_index, end_index, tags FROM subjective "
        "WHERE athlete_id = %s AND activity_id = %s ORDER BY external_id",
        (athlete, aid),
    ).fetchall()
    assert len(rows) == 2
    assert rows[1] == ("502", "Legs heavy on this climb (edited)", 3600, 4200, ["comment"])
    assert rows[0][4] == ["comment", "fuel"]


def test_disagreement_stored_with_platform_value(conn, athlete):
    aid = store(conn, athlete, "activity_platform_carbs")
    run(conn, athlete, FIXTURE["messages"])
    intake = conn.execute(
        "SELECT carbs_g, platform_carbs_g, carbs_differ, fluid_ml, comment_external_id "
        "FROM activity_intake WHERE activity_id = %s",
        (aid,),
    ).fetchone()
    assert intake == (90, 60, True, None, "501")
    view = conn.execute(
        "SELECT carbs_ingested_g, carbs_source, platform_carbs_g "
        "FROM activity_nutrition WHERE activity_id = %s",
        (aid,),
    ).fetchone()
    assert view == (90, "tag", 60)


def test_later_tag_replaces_and_removed_tag_clears(conn, athlete):
    aid = store(conn, athlete, "activity_platform_carbs")
    messages = [dict(m) for m in FIXTURE["messages"]]
    later = {
        **messages[0],
        "id": 503,
        "created": "2026-09-11T13:00:00Z",
        "content": "#fuel 1.5l 240g 1100kcal",
    }
    run(conn, athlete, [*messages, later])
    got = conn.execute(
        "SELECT fluid_ml, carbs_g, kcal FROM activity_intake WHERE activity_id = %s", (aid,)
    ).fetchone()
    assert got == (1500, 240, 1100)
    no_tags = [{**m, "content": "no tag"} for m in messages]
    run(conn, athlete, no_tags)
    assert conn.execute(
        "SELECT count(*) FROM activity_intake WHERE activity_id = %s", (aid,)
    ).fetchone() == (0,)
