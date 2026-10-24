import os
import uuid
from datetime import date, datetime

import httpx
import pytest

from domestique import db
from domestique.ingest import icu, icu_client

ACTIVITY = {
    "id": "i1001",
    "start_date_local": "2026-09-08T17:30:00",
    "start_date": "2026-09-08T15:30:00Z",
    "type": "Ride",
    "name": "synthetic",
    "moving_time": 3000,
    "icu_average_watts": 250,
    "icu_weighted_avg_watts": 260,
    "average_heartrate": 150,
    "max_heartrate": 175,
    "icu_ftp": 300,
    "icu_intensity": 86.7,
    "icu_training_load": 70,
}


def streams_from(ride):
    s = ride["samples"]
    return [
        {"type": "time", "data": [x["t_s"] for x in s]},
        {"type": "watts", "data": [x["watts"] for x in s]},
        {"type": "heartrate", "data": [x["hr"] for x in s]},
        {"type": "cadence", "data": [x["cadence"] for x in s]},
        {"type": "left_right_balance", "data": [x["lr"] for x in s]},
    ]


def test_map_activity_without_streams():
    row = icu.map_activity(ACTIVITY, "iX")
    assert row["external_id"] == "i1001"
    assert row["start_local"] == datetime(2026, 9, 8, 17, 30)
    assert row["start_utc"].utcoffset().total_seconds() == 0
    assert row["if"] == pytest.approx(0.867)
    assert row["np_w"] == 260
    assert row["decoupling"] is None


def test_map_activity_computes_metrics_from_streams(endurance):
    samples = icu.samples_from_streams(streams_from(endurance))
    row = icu.map_activity(ACTIVITY, "iX", samples)
    assert row["decoupling"] == pytest.approx(1.0, abs=0.1)
    assert row["ef"] == pytest.approx(1.53, abs=0.03)
    assert row["lr_balance"] == pytest.approx(50.0)


def test_map_intervals_fills_lr_from_streams(intervals):
    samples = icu.samples_from_streams(streams_from(intervals))
    payload = {
        "icu_intervals": [
            {
                "type": "WORK",
                "start_time": iv["start_s"],
                "elapsed_time": iv["dur_s"],
                "average_watts": 330,
            }
            for iv in intervals["intervals"]
        ]
    }
    rows = icu.map_intervals(payload, samples)
    assert [r["idx"] for r in rows] == list(range(6))
    assert rows[0]["lr_balance"] == pytest.approx(63.0, abs=0.01)
    assert rows[5]["lr_balance"] == pytest.approx(59.0, abs=0.01)
    assert rows[0]["avg_w"] == 330


def test_map_wellness():
    row = icu.map_wellness(
        {"id": "2026-09-08", "hrv": 95, "restingHR": 52, "sleepSecs": 27000, "ctl": 80}, "iX"
    )
    assert row["date"] == date(2026, 9, 8)
    assert (row["hrv"], row["rhr"], row["sleep_s"], row["weight"]) == (95, 52, 27000, None)


def test_client_paths_and_auth():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    http = icu_client.make_client("test-key", transport=httpx.MockTransport(handler))
    c = icu_client.IcuClient("iX", http)
    c.activities("2026-09-01", "2026-09-30")
    c.wellness("2026-09-01", "2026-09-30")
    c.streams("a1", "watts")
    assert seen[0].url.path == "/api/v1/athlete/iX/activities"
    assert seen[0].url.params["oldest"] == "2026-09-01"
    assert seen[1].url.path == "/api/v1/athlete/iX/wellness"
    assert seen[2].url.path == "/api/v1/activity/a1/streams"
    assert seen[0].headers["authorization"].startswith("Basic ")


def test_api_key_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("ICU_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(icu_client.MissingCredentialsError):
        icu_client.get_api_key()


FUEL_COMMENT = {
    "id": 7001,
    "athlete_id": "i000000",
    "name": "Synthetic Athlete",
    "created": "2026-09-08T19:00:00Z",
    "content": "Steady.\n#fuel 750ml 80g",
    "start_index": None,
    "end_index": None,
    "deleted": False,
}


def fake_icu(athlete_id, intervals, messages, activity=None):
    """An IcuClient over a mock transport: activities, streams, intervals, comments, wellness."""
    seen = []
    routes = {
        "/activities": [activity or {**ACTIVITY, "carbs_ingested": 60}],
        "/streams": streams_from(intervals),
        "/intervals": {"icu_intervals": []},
        "/messages": messages,
        "/wellness": [{"id": "2026-09-08", "hrv": 90}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        seen.append(p)
        body = next(v for suffix, v in routes.items() if p.endswith(suffix))
        return httpx.Response(200, json=body)

    http = icu_client.make_client("k", transport=httpx.MockTransport(handler))
    return icu_client.IcuClient(athlete_id, http), seen


@pytest.mark.skipif(not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN")
def test_ingest_is_idempotent(intervals):
    """Integration: set DOMESTIQUE_TEST_DSN to a scratch TimescaleDB database."""
    client, _ = fake_icu("iTest", intervals, [], ACTIVITY)
    with db.connect(os.environ["DOMESTIQUE_TEST_DSN"]) as conn:
        db.migrate(conn)
        for _ in range(2):
            icu.ingest(conn, client, date(2026, 9, 1), date(2026, 9, 30))
        count = lambda t: conn.execute(f"SELECT count(*) FROM {t} WHERE 1=1").fetchone()[0]  # noqa: E731
        assert count("activities") >= 1
        n = conn.execute(
            "SELECT count(*) FROM activities WHERE external_id = 'i1001' AND athlete_id = 'iTest'"
        ).fetchone()[0]
        assert n == 1


@pytest.mark.skipif(not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN")
@pytest.mark.parametrize("with_comments", [True, False])
def test_ingest_stores_comments_and_intake(intervals, with_comments):
    athlete = f"iT{uuid.uuid4().hex[:8]}"
    client, seen = fake_icu(athlete, intervals, [FUEL_COMMENT])
    with db.connect(os.environ["DOMESTIQUE_TEST_DSN"]) as conn:
        db.migrate(conn)
        counts = icu.ingest(
            conn, client, date(2026, 9, 1), date(2026, 9, 30), with_comments=with_comments
        )
        (aid,) = conn.execute(
            "SELECT id FROM activities WHERE athlete_id = %s AND external_id = 'i1001'",
            (athlete,),
        ).fetchone()
        comments = conn.execute(
            "SELECT external_id, tags FROM subjective WHERE athlete_id = %s AND activity_id = %s",
            (athlete, aid),
        ).fetchall()
        intake = conn.execute(
            "SELECT fluid_ml, carbs_g, platform_carbs_g, carbs_differ "
            "FROM activity_intake WHERE activity_id = %s",
            (aid,),
        ).fetchall()
    if with_comments:
        assert counts == {"activities": 1, "comments": 1, "wellness": 1}
        assert seen.count("/api/v1/activity/i1001/messages") == 1
        assert comments == [("7001", ["comment", "fuel"])]
        assert intake == [(750, 80, 60, True)]
    else:
        assert counts == {"activities": 1, "comments": 0, "wellness": 1}
        assert not any(p.endswith("/messages") for p in seen)
        assert (comments, intake) == ([], [])


def test_main_parses_no_comments(monkeypatch):
    calls = {}

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_ingest(conn, client, oldest, newest, with_streams, with_comments):
        calls.update(with_streams=with_streams, with_comments=with_comments)
        return {"activities": 0, "comments": 0, "wellness": 0}

    monkeypatch.setattr(icu, "cli_settings", lambda: ("iX", "postgresql://unused/db"))
    monkeypatch.setattr(icu.db, "connect", lambda dsn: Conn())
    monkeypatch.setattr(icu.db, "migrate", lambda conn: [])
    monkeypatch.setattr(icu.icu_client, "make_client", lambda: None)
    monkeypatch.setattr(icu, "ingest", fake_ingest)
    icu.main(["--from", "2026-09-01", "--no-comments"])
    assert calls == {"with_streams": True, "with_comments": False}
    icu.main(["--from", "2026-09-01"])
    assert calls["with_comments"] is True
