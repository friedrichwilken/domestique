"""web-console 1.1, 3.1, 3.2 against Postgres. Set DOMESTIQUE_TEST_DSN to a scratch database."""

import os
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from domestique import db
from domestique.claims.store import PgStore
from domestique.ingest.plan_store import PgPlanStore
from domestique.loop.model import Metric, Outcome, Prediction
from domestique.loop.store import PgLoopStore
from domestique.web.app import DECIDED_BY, WebSettings, create_app
from domestique.web.day import DaySettings, all_open_questions, load_day_view
from domestique.web.queries import ReportData, from_db

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


# --- web-console 3.1: the day loader ---------------------------------------------

TOKEN = "synthetic-token"
OVERSHOOT = "Did the session as ridden match what you intended for it?"


def question(conn, athlete, text, context=None, status="open"):
    conn.execute(
        'INSERT INTO questions (athlete_id, "for", text, context, status) '
        "VALUES (%s, 'athlete', %s, %s, %s)",
        (athlete, text, Jsonb(context or {}), status),
    )


def test_day_loader_reads_rails_and_the_days_open_questions(conn, athlete):
    conn.execute(
        "INSERT INTO subjective (athlete_id, ts, tags) VALUES (%s, %s, %s)",
        (athlete, datetime(2026, 9, 9, 12, tzinfo=UTC), ["joint-pain"]),
    )
    session(conn, athlete, DAY)
    question(conn, athlete, OVERSHOOT, {"date": DAY.isoformat()})
    question(conn, athlete, "answered already", {"date": DAY.isoformat()}, status="answered")
    question(conn, athlete, "another day", {"date": (DAY + timedelta(days=1)).isoformat()})
    question(conn, f"{athlete}x", "another athlete", {"date": DAY.isoformat()})

    view = load_day_view(conn, athlete, DAY, DaySettings())

    assert [(r.rail, r.action) for r in view.rails] == [("joint-pain", "stop_plan")]
    assert view.withheld_by == ("joint-pain",) and view.sessions == ()
    assert [q.text for q in view.questions] == [OVERSHOOT]


def test_day_loader_joins_the_plan_on_a_quiet_day(conn, athlete):
    session(conn, athlete, DAY)
    question(conn, athlete, "asked today, no date in its context")  # created now: not DAY

    view = load_day_view(conn, athlete, DAY, DaySettings(hr_max=190.0))

    assert view.rails == () and view.questions == ()
    (row,) = view.sessions
    assert row.planned.title == "Endurance" and row.status == "missed"


# --- web-console 3.2: the gate through the Postgres store ---------------------------


@pytest.fixture
def gate(conn, monkeypatch):
    """The app's gate over PgStore on the test connection, rolled back afterwards."""
    monkeypatch.setenv("DOMESTIQUE_HUMAN_TOKEN", TOKEN)

    @contextmanager
    def provide():
        yield PgStore(conn)

    app = create_app(
        WebSettings("unused", None),
        report=lambda: ReportData("unused", ()),
        day=lambda d: pytest.fail("not used"),
        store=provide,
    )
    with TestClient(app) as c:
        yield c


def test_gate_confirms_a_candidate_in_postgres(gate, conn, athlete):
    claims = PgStore(conn)
    c = claims.propose_claim(athlete, "synthetic", "prior", "day", [], "test")
    wrong = gate.post(
        f"/claims/{c.id}/decide", data={"status": "active", "reason": "r", "token": "nope"}
    )
    assert wrong.status_code == 403
    assert claims.query_claims(athlete_id=athlete)[0].status == "candidate"
    assert [h.reason for h in claims.history(c.id)] == ["proposed"]

    ok = gate.post(
        f"/claims/{c.id}/decide",
        data={"status": "active", "reason": "held up", "token": TOKEN},
        follow_redirects=False,
    )

    assert ok.status_code == 303
    assert claims.query_claims(athlete_id=athlete)[0].status == "active"
    last = claims.history(c.id)[-1]
    assert (last.reason, last.by, last.status) == ("held up", DECIDED_BY, "active")
    # chat-layer 1.2: the decision is visible afterwards, as JSON and in the report
    body = gate.get(f"/claims/{c.id}/history.json").json()
    assert [(h["reason"], h["by"]) for h in body["history"]] == [
        ("proposed", "test"),
        ("held up", DECIDED_BY),
    ]
    (report,) = from_db(conn, athlete).claims
    assert [h.reason for h in report.history] == ["proposed", "held up"]
    assert gate.get(f"/claims/{uuid.uuid4()}/history.json").status_code == 404


# --- chat-layer 1.1: every open question ------------------------------------------


def test_all_open_questions_reads_every_open_question_of_the_athlete(conn, athlete):
    question(conn, athlete, OVERSHOOT, {"date": DAY.isoformat()})
    question(conn, athlete, "no date in its context")
    question(conn, athlete, "answered already", status="answered")
    question(conn, f"{athlete}x", "another athlete")

    texts = [q.text for q in all_open_questions(conn, athlete)]

    assert sorted(texts) == sorted([OVERSHOOT, "no date in its context"])
