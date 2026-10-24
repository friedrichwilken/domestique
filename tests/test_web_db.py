"""web-console 1.1: from_db against Postgres. Set DOMESTIQUE_TEST_DSN to a scratch database."""

import os
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from domestique import db
from domestique.claims.store import PgStore
from domestique.ingest.plan_store import PgPlanStore
from domestique.loop.model import Metric, Outcome, Prediction
from domestique.loop.store import PgLoopStore
from domestique.web.queries import from_db

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


def session(conn, athlete, day):
    return PgPlanStore(conn).upsert_planned(
        {
            "athlete_id": athlete,
            "source": "test",
            "external_id": uuid.uuid4().hex,
            "date": day,
            "start_local": datetime(day.year, day.month, day.day, 18),
            "sport": "Ride",
            "title": "Endurance",
            "description": None,
            "structure": None,
            "planned_tss": 60.0,
            "planned_if": 0.7,
            "planned_moving_s": 3600,
            "raw": {},
        }
    )


def active(claims, athlete, text):
    c = claims.propose_claim(athlete, text, "observed", "day", [], "test", 0.5)
    return claims.confirm_or_retire(c.id, "active", "test setup", "human")


def predict(loop, sid, claim_id, metric, official, actual=None):
    p = Prediction(sid, metric, 100.0, 95.0, 105.0, (claim_id,), official=official)
    (saved,) = loop.save_predictions([p])
    if actual is not None:
        loop.record_outcome(Outcome(saved.id, actual, actual - 100.0))
    return saved


def test_from_db_two_claims_three_scored_predictions(conn, athlete):
    claims, loop = PgStore(conn), PgLoopStore(conn)
    first, second = active(claims, athlete, "first"), active(claims, athlete, "second")
    claims.record_adjustment(
        replace(first, scored=2, hits=1, calib_scored=2, calib_abs_error=6.0, calib_half_range=10),
        "test",
        "test",
    )
    s1, s2, s3 = (session(conn, athlete, DAY + timedelta(days=d)) for d in (0, 1, 2))
    predict(loop, s2, first.id, Metric.PEAK_HR, True, actual=110.0)  # miss
    predict(loop, s1, first.id, Metric.PEAK_HR, True, actual=101.0)  # hit, earlier day
    predict(loop, s1, second.id, Metric.PEAK_HR, False, actual=99.0)  # shadow hit
    predict(loop, s3, second.id, Metric.PEAK_HR, True)  # not scored yet: left out
    other = active(claims, f"{athlete}x", "another athlete's claim")
    predict(loop, s3, other.id, Metric.WATTS_AT_HR, True, actual=100.0)

    data = from_db(conn, athlete)

    assert data.athlete_id == athlete
    by_text = {c.text: c for c in data.claims}  # one transaction: created_at ties
    assert sorted(by_text) == ["first", "second"]
    a, b = by_text["first"], by_text["second"]
    assert [(p.day, p.actual, p.hit) for p in a.predictions] == [
        (DAY, 101.0, True),
        (DAY + timedelta(days=1), 110.0, False),
    ]
    assert a.predictions[1].miss_by == pytest.approx(5.0)
    assert (a.scored, a.hits, a.hit_rate, a.error_share) == (2, 1, 0.5, pytest.approx(0.6))
    assert [(p.official, p.low, p.high, p.expected) for p in b.predictions] == [
        (False, 95.0, 105.0, 100.0)
    ]
    assert b.error_share is None
