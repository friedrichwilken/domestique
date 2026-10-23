"""Integration: set DOMESTIQUE_TEST_DSN to a scratch TimescaleDB database."""

import os
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta

import psycopg
import pytest

from domestique import db
from domestique.analysis.plan_vs_execution import plan_vs_execution
from domestique.claims.store import PgStore
from domestique.ingest.plan_store import PgPlanStore
from domestique.loop.load import load_actuals, load_history
from domestique.loop.model import Binding, Metric
from domestique.loop.predict import predict
from domestique.loop.score import overshoot_flag, score_session
from domestique.loop.store import PgLoopStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN"
)

DAY = date(2026, 9, 9)
HR_MAX = 190


@pytest.fixture
def conn():
    with db.connect(os.environ["DOMESTIQUE_TEST_DSN"]) as c:
        db.migrate(c)
        yield c
        c.rollback()


@pytest.fixture
def athlete():
    return f"iT{uuid.uuid4().hex[:8]}"


def activity(conn, athlete, start, max_hr, watts, hr, work_hr=None):
    (aid,) = conn.execute(
        "INSERT INTO activities (athlete_id, source, external_id, start_local, sport, max_hr) "
        "VALUES (%s, 'test', %s, %s, 'Ride', %s) RETURNING id",
        (athlete, uuid.uuid4().hex, start, max_hr),
    ).fetchone()
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO activity_streams (activity_id, t_s, watts, hr) VALUES (%s, %s, %s, %s)",
            [(aid, t, watts, hr) for t in range(600)],
        )
    if work_hr is not None:
        conn.execute(
            "INSERT INTO activity_intervals (activity_id, idx, kind, dur_s, avg_hr) "
            "VALUES (%s, 0, 'WORK', 1800, %s)",
            (aid, work_hr),
        )
    return aid


def plan(conn, athlete, paired):
    store = PgPlanStore(conn)
    pid = store.upsert_planned(
        {
            "athlete_id": athlete,
            "source": "test",
            "external_id": uuid.uuid4().hex,
            "date": DAY,
            "start_local": datetime(2026, 9, 9, 18),
            "sport": "Ride",
            "title": "Endurance",
            "description": "Endurance, 60-70% of max heart rate",
            "structure": None,
            "planned_tss": 80.0,
            "planned_if": 0.7,
            "planned_moving_s": 5400,
            "raw": {},
        }
    )
    conn.execute("UPDATE planned_sessions SET paired_activity_id = %s WHERE id = %s", (paired, pid))
    return store.planned_on(athlete, DAY)[0]


def active_claim(conn, athlete, confidence=0.5):
    claims = PgStore(conn)
    c = claims.propose_claim(athlete, "synthetic", "observed", "day", [], "test", confidence)
    return claims, claims.confirm_or_retire(c.id, "active", "test setup", "human")


def seed(conn, athlete, work_hr, max_hr):
    for days, w in ((3, 200.0), (2, 210.0), (1, 220.0)):
        activity(conn, athlete, datetime(2026, 9, 9, 8) - timedelta(days=days), 150, w, 125.0)
    aid = activity(conn, athlete, datetime(2026, 9, 9, 18, 5), max_hr, 215.0, 125.0, work_hr)
    conn.execute(
        "INSERT INTO wellness (athlete_id, date, hrv, sleep_s, source) "
        "VALUES (%s, %s, 70, 27000, 'test')",
        (athlete, DAY + timedelta(days=1)),
    )
    return plan(conn, athlete, aid)


def predict_and_save(conn, athlete, session, claim_id):
    loop = PgLoopStore(conn)
    loop.add_binding(Binding(claim_id, Metric.PEAK_HR, offset=10, range_abs=4))
    loop.add_binding(Binding(claim_id, Metric.WATTS_AT_HR, range_pct=5, rides=3))
    claims = PgStore(conn).query_claims(athlete_id=athlete, status="active")
    history = load_history(conn, athlete, session, HR_MAX, {})
    result = predict(session, claims, loop.bindings(athlete), history)
    saved = loop.save_predictions(result.predictions)
    return loop, result, saved


def test_predictions_recorded_once_and_scored_once(conn, athlete):
    session = seed(conn, athlete, work_hr=125.0, max_hr=170)
    claims, c = active_claim(conn, athlete)
    loop, result, saved = predict_and_save(conn, athlete, session, c.id)
    assert {p.metric for p in saved} == {Metric.PEAK_HR, Metric.WATTS_AT_HR}
    watts = next(p for p in saved if p.metric == Metric.WATTS_AT_HR)
    assert watts.expected == 210.0 and len(watts.basis["rides"]) == 3
    assert {g.metric for g in result.gaps} == {Metric.HRV_NEXT_MORNING, Metric.SLEEP_HOURS}
    assert loop.save_predictions(result.predictions) == []

    actuals = load_actuals(conn, athlete, session)
    _, applied = score_session(athlete, session, loop, claims, actuals, None)
    # peak HR 170 against 143 +/- 4 misses; watts 215 inside 199.5-220.5 hits
    assert (applied.outcomes, applied.adjustments) == (2, 2)
    _, again = score_session(athlete, session, loop, claims, actuals, None)
    assert again.outcomes == 0 and again.adjustments == 0
    (n,) = conn.execute(
        "SELECT count(*) FROM outcomes o JOIN predictions p ON p.id = o.prediction_id "
        "WHERE p.planned_session_id = %s",
        (session.id,),
    ).fetchone()
    assert n == 2
    after = claims.query_claims(athlete_id=athlete)[0]
    assert after.confidence == 0.45  # miss (0.5 -> 0.35) then hit (-> 0.45), metric order
    reasons = [h.reason for h in claims.history(c.id)]
    assert any(p.id in r for p in saved for r in reasons)


def test_overshoot_miss_writes_a_question_and_leaves_the_claim(conn, athlete):
    session = seed(conn, athlete, work_hr=171.0, max_hr=185)
    claims, c = active_claim(conn, athlete)
    loop, _, _ = predict_and_save(conn, athlete, session, c.id)
    rows = plan_vs_execution(PgPlanStore(conn), athlete, DAY, HR_MAX)
    flag = overshoot_flag(rows, session.id)
    assert flag is not None
    actuals = load_actuals(conn, athlete, session)
    _, applied = score_session(athlete, session, loop, claims, actuals, flag)
    assert applied.adjustments == 0 and applied.questions == 1
    assert claims.query_claims(athlete_id=athlete)[0].confidence == 0.5
    saved = conn.execute(
        "SELECT \"for\", context->>'kind' FROM questions WHERE athlete_id = %s", (athlete,)
    ).fetchall()
    assert saved == [("athlete", "prediction_loop.overshoot_miss")]


def test_predictions_need_a_real_planned_session(conn, athlete):
    _, c = active_claim(conn, athlete)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO predictions (planned_session_id, metric, claim_id, official, expected, "
            "low, high) VALUES (-1, 'peak_hr', %s, true, 150, 145, 155)",
            (c.id,),
        )


def test_shadow_predictions_stored_with_one_official_per_metric(conn, athlete):
    session = seed(conn, athlete, work_hr=125.0, max_hr=170)
    claims, c = active_claim(conn, athlete, confidence=0.6)
    rival = claims.confirm_or_retire(
        claims.propose_claim(athlete, "rival", "observed", "day", [], "test", 0.4).id,
        "active",
        "test setup",
        "human",
    )
    loop = PgLoopStore(conn)
    loop.add_binding(Binding(c.id, Metric.PEAK_HR, offset=10, range_abs=4))
    loop.add_binding(Binding(rival.id, Metric.PEAK_HR, offset=30, range_abs=4))
    active = claims.query_claims(athlete_id=athlete, status="active")
    history = load_history(conn, athlete, session, HR_MAX, {})
    result = predict(session, active, loop.bindings(athlete), history)
    assert len(loop.save_predictions(result.predictions)) == 2
    listed = loop.predictions_for(session.id)
    assert [(p.claim_id, p.official) for p in listed] == [(c.id, True), (rival.id, False)]
    # the rival now outranks: re-predicting keeps the first official, adds nothing
    boosted = [replace(x, confidence=0.9) if x.id == rival.id else x for x in active]
    again = predict(session, boosted, loop.bindings(athlete), history)
    assert loop.save_predictions(again.predictions) == []
    with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
        conn.execute(
            "UPDATE predictions SET official = true WHERE planned_session_id = %s",
            (session.id,),
        )
    # peak 170: official (143 +/- 4) misses, the shadow (163 +/- 4) misses too; both scored
    actuals = load_actuals(conn, athlete, session)
    _, applied = score_session(athlete, session, loop, claims, actuals, None)
    assert (applied.outcomes, applied.adjustments) == (2, 2)
    after = {x.id: x for x in claims.query_claims(athlete_id=athlete)}
    assert after[rival.id].scored == 1 and after[rival.id].calib_half_range == 4.0
    assert after[c.id].calib_abs_error == 27.0
