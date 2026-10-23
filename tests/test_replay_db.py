"""Integration: the replay over ingested history. Set DOMESTIQUE_TEST_DSN to a scratch TimescaleDB.

The fixture season is loaded into the database as if ingested, then replayed
through ``--source db``: the numbers must match the fixture replay, a review
list must be written, and the claims store must stay untouched.
"""

import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path

import psycopg
import pytest
import yaml

from domestique import db
from domestique.ingest.plan_store import PgPlanStore
from domestique.replay.fixture import FixtureSeason, expand
from domestique.replay.pg import open_readonly
from domestique.replay.report import headline, planted_effect
from domestique.replay.run import main

pytestmark = pytest.mark.skipif(
    not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN"
)

ROOT = Path(__file__).resolve().parents[1]
SEASON = ROOT / "evals/fixtures/season_a"
COUNTS = (
    "SELECT (SELECT count(*) FROM claims WHERE athlete_id = %(a)s), "
    "(SELECT count(*) FROM claim_bindings b JOIN claims c ON c.id = b.claim_id "
    "WHERE c.athlete_id = %(a)s), "
    "(SELECT count(*) FROM predictions p JOIN planned_sessions s ON s.id = p.planned_session_id "
    "WHERE s.athlete_id = %(a)s), "
    "(SELECT count(*) FROM questions WHERE athlete_id = %(a)s)"
)


def _rows(name):
    return json.loads((SEASON / name).read_text())


def _activity(conn, athlete, a):
    (aid,) = conn.execute(
        "INSERT INTO activities (athlete_id, source, external_id, start_local, sport, max_hr, "
        "moving_s) VALUES (%s, 'fixture', %s, %s, %s, %s, %s) RETURNING id",
        (
            athlete,
            str(a["id"]),
            datetime.fromisoformat(a["start_local"]),
            a["sport"],
            a["max_hr"],
            a["moving_s"],
        ),
    ).fetchone()
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO activity_intervals "
            "(activity_id, idx, kind, start_s, dur_s, avg_w, avg_hr) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (aid, i["idx"], i["kind"], i["start_s"], i["dur_s"], i["avg_w"], i["avg_hr"])
                for i in a["intervals"]
            ],
        )
        with cur.copy("COPY activity_streams (activity_id, t_s, watts, hr) FROM STDIN") as cp:
            for s in expand(a["segments"]):
                cp.write_row((aid, int(s["t_s"]), s["watts"], s["hr"]))
    return aid


def _planned(conn, athlete, p, ids):
    pid = PgPlanStore(conn).upsert_planned(
        {
            "athlete_id": athlete,
            "source": "fixture",
            "external_id": str(p["id"]),
            "date": date.fromisoformat(p["date"]),
            "start_local": datetime.fromisoformat(p["start_local"]),
            "sport": p["sport"],
            "title": p["title"],
            "description": p["description"],
            "structure": None,
            "planned_tss": p["planned_tss"],
            "planned_if": p["planned_if"],
            "planned_moving_s": p["planned_moving_s"],
            "raw": {},
        }
    )
    if p["paired_activity_id"] is not None:
        conn.execute(
            "UPDATE planned_sessions SET paired_activity_id = %s WHERE id = %s",
            (ids[p["paired_activity_id"]], pid),
        )


def load_season(conn, athlete):
    ids = {a["id"]: _activity(conn, athlete, a) for a in _rows("activities.json")}
    for p in _rows("planned.json"):
        _planned(conn, athlete, p, ids)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO wellness (athlete_id, date, hrv, rhr, sleep_s, source) "
            "VALUES (%s, %s, %s, %s, %s, 'fixture')",
            [
                (athlete, date.fromisoformat(w["date"]), w["hrv"], w["rhr"], w["sleep_s"])
                for w in _rows("wellness.json")
            ],
        )


def remove_season(conn, athlete):
    conn.execute("DELETE FROM planned_sessions WHERE athlete_id = %s", (athlete,))
    conn.execute("DELETE FROM activities WHERE athlete_id = %s", (athlete,))
    conn.execute("DELETE FROM wellness WHERE athlete_id = %s", (athlete,))
    conn.commit()


@pytest.fixture
def ingested():
    dsn = os.environ["DOMESTIQUE_TEST_DSN"]
    athlete = f"iR{uuid.uuid4().hex[:8]}"
    with db.connect(dsn) as conn:
        db.migrate(conn)
        load_season(conn, athlete)
        conn.commit()
        try:
            yield dsn, athlete, conn
        finally:
            conn.rollback()
            remove_season(conn, athlete)


def test_bootstrap_over_ingested_history_writes_only_the_review_file(
    ingested, tmp_path, monkeypatch
):
    dsn, athlete, conn = ingested
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "athlete_id": athlete,
                "timezone": "UTC",
                "bedtime": "22:30",
                "hr_max": 190,
                "database_url": dsn,
            }
        )
    )
    monkeypatch.setenv("DOMESTIQUE_HOME", str(home))
    before = conn.execute(COUNTS, {"a": athlete}).fetchone()
    conn.commit()
    season = FixtureSeason(SEASON)
    out = tmp_path / "out"
    written = main(
        [
            "--source",
            "db",
            "--from",
            season.first.isoformat(),
            "--to",
            season.last.isoformat(),
            "--out",
            str(out),
        ],
        repo=ROOT,
    )
    review = yaml.safe_load((out / "review.yaml").read_text())
    assert review["candidates"] and review["athlete_id"] == athlete
    assert all(c["status"] == "candidate" for c in review["candidates"])
    assert conn.execute(COUNTS, {"a": athlete}).fetchone() == before == (0, 0, 0, 0)
    # same data, same loop: the database replay reproduces the fixture replay
    fixture = main(["--out", str(tmp_path / "fixture")], repo=ROOT)
    assert headline(written.result) == headline(fixture.result)
    assert planted_effect(written.result) == planted_effect(fixture.result)


def test_history_connection_refuses_writes(ingested):
    dsn, athlete, _ = ingested
    with open_readonly(dsn) as conn, pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute(
            "INSERT INTO wellness (athlete_id, date, source) VALUES (%s, '2026-01-01', 't')",
            (athlete,),
        )
