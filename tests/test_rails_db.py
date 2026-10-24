"""Integration: set DOMESTIQUE_TEST_DSN to a scratch TimescaleDB database."""

import os
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from domestique import db
from domestique.rails.load import load_day

pytestmark = pytest.mark.skipif(
    not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN"
)

DAY = date(2026, 9, 9)


@pytest.fixture
def conn():
    with db.connect(os.environ["DOMESTIQUE_TEST_DSN"]) as c:
        db.migrate(c)
        yield c
        c.rollback()


@pytest.fixture
def athlete():
    return f"iT{uuid.uuid4().hex[:8]}"


def wellness(conn, athlete, day, hrv, ctl):
    conn.execute(
        "INSERT INTO wellness (athlete_id, date, hrv, ctl, source) VALUES (%s, %s, %s, %s, 'test')",
        (athlete, day, hrv, ctl),
    )


def test_loader_reads_the_day(conn, athlete):
    wellness(conn, athlete, DAY, 61.5, 70.0)
    wellness(conn, athlete, DAY - timedelta(days=7), 80.0, 62.0)
    # 23:30 UTC on the day before is 01:30 on the day in Berlin summer time
    late = datetime(2026, 9, 8, 23, 30, tzinfo=UTC)
    conn.execute(
        "INSERT INTO subjective (athlete_id, ts, tags) VALUES (%s, %s, %s)",
        (athlete, late, ["joint-pain", "legs-heavy"]),
    )
    conn.execute(
        "INSERT INTO context (athlete_id, date, kind) VALUES (%s, %s, 'illness')", (athlete, DAY)
    )

    day = load_day(conn, athlete, DAY, "Europe/Berlin")

    assert day.hrv == 61.5
    assert day.ctl_delta_7d == pytest.approx(8.0)
    assert day.subjective_tags == ("joint-pain", "legs-heavy")
    assert day.context_kinds == ("illness",)
    assert load_day(conn, athlete, DAY, "UTC").subjective_tags == ()


def test_empty_day_stays_at_defaults(conn, athlete):
    day = load_day(conn, athlete, DAY)
    assert (day.hrv, day.ctl_delta_7d, day.subjective_tags, day.context_kinds) == (
        None,
        None,
        (),
        (),
    )
