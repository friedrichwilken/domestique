import os
import re
from datetime import date, datetime

import pytest

from domestique import db
from domestique.analysis.plan_vs_execution import (
    parse_hr_guidance,
    plan_vs_execution,
    questions_of,
    save_questions,
    work_hr_pct,
)
from domestique.ingest.icu_plan import ingest_planned
from domestique.ingest.plan_store import ExecutedSession, MemoryPlanStore, WorkInterval

HR_MAX = 190.0
DAY = date(2026, 9, 9)

PLANS = [
    {
        "id": 1,
        "category": "WORKOUT",
        "start_date_local": "2026-09-09T07:00:00",
        "name": "Morning endurance",
        "description": "Easy, 60-70% of max heart rate",
        "type": "Ride",
    },
    {
        "id": 2,
        "category": "WORKOUT",
        "start_date_local": "2026-09-09T18:00:00",
        "name": "Sweet spot 3x12",
        "description": "Sweet spot blocks, ca. 75% HFmax",
        "type": "Ride",
    },
]


class FakeEvents:
    athlete_id = "iTest"

    def events(self, oldest, newest):
        return PLANS


def session(aid, start, work_hr, np_w=240.0):
    work = tuple(WorkInterval(720, hr) for hr in work_hr)
    return ExecutedSession(
        aid, "Ride", datetime.fromisoformat(start), np_w, 140.0, 182.0, 0.82, work
    )


def build(evening_work_hr):
    store = MemoryPlanStore()
    store.add_activity("iTest", session(11, "2026-09-09T07:15:00", [125.0]))
    store.add_activity("iTest", session(12, "2026-09-09T18:05:00", evening_work_hr, 290.0))
    ingest_planned(store, FakeEvents(), DAY, DAY)
    return store


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("ca. 75% HFmax", 75, 75),
        ("60-75% of max", 60, 75),
        ("60 \u2013 75 % HRmax", 60, 75),
        ("~75% of max heart rate", 75, 75),
        ("at 80% max HR", 80, 80),
    ],
)
def test_parse_hr_guidance(text, low, high):
    g = parse_hr_guidance(text)
    assert g is not None
    assert (g.low_pct, g.high_pct) == (low, high)


@pytest.mark.parametrize("text", [None, "", "3x12 min at 90% FTP", "Tempo blocks"])
def test_no_hr_guidance(text):
    assert parse_hr_guidance(text) is None


def test_work_hr_pct_is_duration_weighted():
    ivs = [WorkInterval(600, 171.0), WorkInterval(200, 133.0), WorkInterval(100, None)]
    assert work_hr_pct(ivs, 190.0) == pytest.approx(100 * (600 * 171 + 200 * 133) / 800 / 190)
    assert work_hr_pct([], 190.0) is None


def test_paired_double_day_returns_both_sides():
    rows = plan_vs_execution(build([140.0]), "iTest", DAY, HR_MAX)
    assert len(rows) == 2
    morning, evening = rows
    assert morning.planned.title == "Morning endurance"
    assert morning.hr_guidance is not None and morning.hr_guidance.high_pct == 70
    assert morning.executed is not None and morning.executed.id == 11
    assert evening.executed is not None and evening.executed.id == 12
    assert evening.executed.np_w == 290.0
    assert (evening.executed.avg_hr, evening.executed.max_hr) == (140.0, 182.0)
    assert evening.executed.intensity_factor == 0.82
    assert all(r.status == "paired" for r in rows)
    assert questions_of(rows) == []


def test_sweet_spot_text_vo2_execution_yields_a_question():
    # 171 bpm of 190 = 90% of max in the work intervals, prescription ~75%
    rows = plan_vs_execution(build([171.0, 171.0, 171.0]), "iTest", DAY, HR_MAX)
    (q,) = questions_of(rows)
    assert q.for_ == "athlete"
    assert q.athlete_id == "iTest"
    assert "75%" in q.text and "90%" in q.text
    assert q.text.rstrip().endswith("?")
    judgement = r"\b(error|mistake|wrong|too|over\w*|should|fail\w*|exceed\w*|ignored)\b"
    assert not re.search(judgement, q.text, re.I)
    assert q.context["prescribed_hr_pct_high"] == 75
    assert q.context["executed_work_hr_pct"] == pytest.approx(90.0)
    assert q.context["planned_session_id"] == rows[1].planned.id
    assert q.context["activity_id"] == 12


def test_margin_is_configurable():
    store = build([160.0])  # 84% of max against ~75%: inside 10 pp, outside 5 pp
    assert questions_of(plan_vs_execution(store, "iTest", DAY, HR_MAX)) == []
    assert len(questions_of(plan_vs_execution(store, "iTest", DAY, HR_MAX, margin_pp=5))) == 1


def test_unpaired_plan_is_missed_without_question():
    store = MemoryPlanStore()
    ingest_planned(store, FakeEvents(), DAY, DAY)
    rows = plan_vs_execution(store, "iTest", DAY, HR_MAX)
    assert [r.status for r in rows] == ["missed", "missed"]
    assert all(r.executed is None and r.work_hr_pct is None for r in rows)
    assert questions_of(rows) == []


def test_no_hr_max_means_no_overshoot_check():
    rows = plan_vs_execution(build([171.0]), "iTest", DAY, None)
    assert rows[1].work_hr_pct is None
    assert questions_of(rows) == []


@pytest.mark.skipif(not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN")
def test_questions_are_saved_as_open_rows():
    """Integration: set DOMESTIQUE_TEST_DSN to a scratch TimescaleDB database."""
    rows = plan_vs_execution(build([171.0]), "iTest", DAY, HR_MAX)
    with db.connect(os.environ["DOMESTIQUE_TEST_DSN"]) as conn:
        db.migrate(conn)
        save_questions(conn, questions_of(rows))
        saved = conn.execute(
            "SELECT \"for\", status, context->>'executed_work_hr_pct' FROM questions "
            "WHERE athlete_id = 'iTest'"
        ).fetchall()
        conn.rollback()
    assert saved == [("athlete", "open", "90.0")]
