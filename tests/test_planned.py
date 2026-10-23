import json
import os
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from domestique import db
from domestique.ingest import icu, icu_client, icu_plan
from domestique.ingest.pairing import ActivityRef, PlanRef, pair
from domestique.ingest.plan_store import ExecutedSession, MemoryPlanStore, PgPlanStore

FIXTURES = Path(__file__).parent.parent / "evals" / "fixtures"
EVENTS = json.loads((FIXTURES / "icu_events_week.json").read_text())
WEEK = (date(2026, 9, 7), date(2026, 9, 13))


class FakeEvents:
    athlete_id = "iTest"

    def __init__(self, events):
        self._events = events
        self.calls = []

    def events(self, oldest, newest):
        self.calls.append((oldest, newest))
        return self._events


def ride(aid, start, sport="Ride"):
    return ExecutedSession(aid, sport, datetime.fromisoformat(start), 250, 150, 170, 0.8)


def test_map_event_keeps_workouts_only():
    rows = icu_plan.map_events(EVENTS, "iTest")
    assert [r["external_id"] for r in rows] == ["9001", "9003", "9004", "9005"]
    first = rows[0]
    assert first["date"] == date(2026, 9, 7)
    assert first["planned_tss"] == 95
    assert first["planned_if"] == pytest.approx(0.66)
    assert first["planned_moving_s"] == 7200
    assert first["structure"] == EVENTS[0]["workout_doc"]
    assert first["raw"] == EVENTS[0]
    assert rows[3]["planned_if"] is None and rows[3]["structure"] is None


def test_ingest_is_idempotent_with_double_day():
    store = MemoryPlanStore()
    source = FakeEvents(EVENTS)
    first = icu_plan.ingest_planned(store, source, *WEEK)
    snapshot = dict(store.planned)
    second = icu_plan.ingest_planned(store, source, *WEEK)
    assert first == second == {"planned": 4, "paired": 0, "missed": 4}
    assert store.planned == snapshot
    assert source.calls == [("2026-09-07", "2026-09-13")] * 2
    double = store.planned_on("iTest", date(2026, 9, 9))
    assert [s.title for s in double] == ["Double day", "Double day"]
    assert len({s.id for s in double}) == 2


def test_double_day_pairs_by_start_time():
    store = MemoryPlanStore()
    store.add_activity("iTest", ride(2, "2026-09-09T18:20:00"))
    store.add_activity("iTest", ride(1, "2026-09-09T07:10:00", sport="VirtualRide"))
    store.add_activity("iTest", ride(3, "2026-09-07T10:00:00"))
    store.add_activity("iOther", ride(4, "2026-09-11T10:00:00"))
    counts = icu_plan.ingest_planned(store, FakeEvents(EVENTS), *WEEK)
    assert counts == {"planned": 4, "paired": 3, "missed": 1}
    morning, evening = store.planned_on("iTest", date(2026, 9, 9))
    assert (morning.paired_activity_id, evening.paired_activity_id) == (1, 2)
    (tempo,) = store.planned_on("iTest", date(2026, 9, 11))
    assert tempo.paired_activity_id is None  # missed, still stored


def test_untimed_double_day_pairs_each_plan_to_a_different_ride():
    plans = [PlanRef(1, date(2026, 9, 9), "Ride", None), PlanRef(2, date(2026, 9, 9), "Ride", None)]
    acts = [
        ActivityRef(20, "Ride", datetime(2026, 9, 9, 17)),
        ActivityRef(10, "Ride", datetime(2026, 9, 9, 8)),
    ]
    result = pair(plans, acts)
    assert result.paired == {1: 10, 2: 20}
    assert result.missed == ()


def test_unpaired_plan_is_missed_and_other_sport_or_day_does_not_pair():
    plans = [PlanRef(1, date(2026, 9, 9), "Ride", datetime(2026, 9, 9, 7))]
    acts = [
        ActivityRef(10, "Run", datetime(2026, 9, 9, 7)),
        ActivityRef(11, "Ride", datetime(2026, 9, 10, 7)),
    ]
    result = pair(plans, acts)
    assert result.paired == {}
    assert result.missed == (1,)


def test_more_rides_than_plans_takes_the_closest():
    plans = [PlanRef(1, date(2026, 9, 9), "Ride", datetime(2026, 9, 9, 18))]
    acts = [
        ActivityRef(10, "Ride", datetime(2026, 9, 9, 7)),
        ActivityRef(11, "Ride", datetime(2026, 9, 9, 17, 45)),
    ]
    assert pair(plans, acts).paired == {1: 11}


def test_events_client_path_and_params():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=EVENTS)

    http = icu_client.make_client("test-key", transport=httpx.MockTransport(handler))
    rows = icu_plan.IcuEvents("iX", http).events("2026-09-07", "2026-09-13")
    assert seen[0].url.path == "/api/v1/athlete/iX/events"
    assert seen[0].url.params["oldest"] == "2026-09-07"
    assert seen[0].url.params["newest"] == "2026-09-13"
    assert len(rows) == len(EVENTS)


@pytest.mark.skipif(not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN")
def test_pg_ingest_is_idempotent_and_pairs():
    """Integration: set DOMESTIQUE_TEST_DSN to a scratch TimescaleDB database."""
    with db.connect(os.environ["DOMESTIQUE_TEST_DSN"]) as conn:
        db.migrate(conn)
        athlete = "iPlanTest"
        conn.execute("DELETE FROM planned_sessions WHERE athlete_id = %s", (athlete,))
        conn.execute("DELETE FROM activities WHERE athlete_id = %s", (athlete,))
        for ext, start in (("a1", "2026-09-09T07:05:00"), ("a2", "2026-09-09T18:10:00")):
            payload = {"id": ext, "start_date_local": start, "type": "Ride"}
            icu.store_activity(conn, icu.map_activity(payload, athlete), [], [])
        source = FakeEvents(EVENTS)
        source.athlete_id = athlete
        store = PgPlanStore(conn)
        for _ in range(2):
            counts = icu_plan.ingest_planned(store, source, *WEEK)
        assert counts == {"planned": 4, "paired": 2, "missed": 2}
        n = conn.execute(
            "SELECT count(*) FROM planned_sessions WHERE athlete_id = %s", (athlete,)
        ).fetchone()[0]
        assert n == 4
        morning, evening = store.planned_on(athlete, date(2026, 9, 9))
        assert morning.paired_activity_id != evening.paired_activity_id
        ext = conn.execute(
            "SELECT external_id FROM activities WHERE id = %s", (morning.paired_activity_id,)
        ).fetchone()[0]
        assert ext == "a1"
        conn.rollback()
