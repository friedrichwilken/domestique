"""web-console 3.1: the day view through the test client, with injected providers."""

import html
import re
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from domestique.analysis.plan_vs_execution import questions_of
from domestique.ingest.icu_plan import ingest_planned
from domestique.ingest.plan_store import ExecutedSession, MemoryPlanStore, WorkInterval
from domestique.rails import DayData, joint_pain
from domestique.web.app import WebSettings, create_app
from domestique.web.day import DaySettings, OpenQuestion, build_day, order_rails
from domestique.web.queries import ReportData

ATHLETE = "iTest"
DAY = date(2026, 9, 9)
SETTINGS = DaySettings(baselines={"hrv": 80.0}, hr_max=190.0, margin_pp=5.0)
PLAN = {
    "id": 2,
    "category": "WORKOUT",
    "start_date_local": "2026-09-09T18:00:00",
    "name": "Sweet spot 3x12",
    "description": "Sweet spot blocks, ca. 75% HFmax",
    "type": "Ride",
}


class FakeEvents:
    athlete_id = ATHLETE

    def events(self, oldest, newest):
        return [PLAN]


def plans() -> MemoryPlanStore:
    store = MemoryPlanStore()
    ride = ExecutedSession(
        12, "Ride", datetime(2026, 9, 9, 18, 5), 290.0, 150.0, 182.0, 0.82,
        (WorkInterval(720, 160.0),),
    )  # fmt: skip
    store.add_activity(ATHLETE, ride)
    ingest_planned(store, FakeEvents(), DAY, DAY)
    return store


def overshoot_text() -> str:
    """The question the join asks for this ride, as ``--save`` would store it."""
    quiet = build_day(ATHLETE, DayData(DAY), SETTINGS, plans())
    (q,) = questions_of(quiet.sessions)
    return q.text


def asked(text: str) -> OpenQuestion:
    return OpenQuestion("q-1", "athlete", text, datetime(2026, 9, 9, 20, tzinfo=UTC))


def client_for(view_for, today=lambda: DAY):
    app = create_app(
        WebSettings(ATHLETE, None),
        report=lambda: ReportData(ATHLETE, ()),
        day=view_for,
        today=today,
        store=lambda: pytest.fail("the day view never opens the claims store"),
    )
    return TestClient(app)


@pytest.fixture
def stopped():
    """A day with a reported joint-pain tag, a planned and ridden session and its question."""
    data = DayData(DAY, subjective_tags=("joint-pain",), hrv=40.0)
    return build_day(ATHLETE, data, SETTINGS, plans(), [asked(overshoot_text())])


def test_triggered_rail_and_question_render_verbatim_and_the_ride_analysis_is_withheld(stopped):
    with client_for(lambda d: stopped) as c:
        page = c.get(f"/day/{DAY}").text
    text = html.unescape(page)
    wording = joint_pain(DayData(DAY, subjective_tags=("joint-pain",)), {}).wording
    assert wording in text
    assert overshoot_text() in text
    assert "withheld because the rail joint-pain fired" in text
    assert '<table class="sessions"' not in page and "290 W" not in page
    rails = re.findall(r'data-rail="([^"]+)"', page)
    assert rails == ["joint-pain", "hrv-floor"]  # the stop comes first, the rest still renders


def test_quiet_day_shows_plan_versus_execution_rows():
    view = build_day(ATHLETE, DayData(DAY), SETTINGS, plans())
    with client_for(lambda d: view) as c:
        page = c.get(f"/day/{DAY}").text
    row = re.search(r'<tr class="session">.*?</tr>', page, re.S).group(0)
    assert "Sweet spot 3x12" in row and "290 W" in row and "84% of max" in row
    assert "No rail triggered." in page and "No open question." in page


def test_withholding_rails_sort_first_in_registry_order():
    data = DayData(DAY, subjective_tags=("joint-pain",), hrv=40.0, context_kinds=("illness",))
    view = build_day(ATHLETE, data, SETTINGS, plans())
    assert [r.rail for r in view.rails] == ["joint-pain", "illness", "hrv-floor"]
    assert view.withheld_by == ("joint-pain", "illness")
    assert view.sessions == ()
    assert order_rails([]) == ()


def test_json_carries_the_same_data(stopped):
    with client_for(lambda d: stopped) as c:
        body = c.get(f"/day/{DAY}.json").json()
    assert body["date"] == "2026-09-09"
    assert [r["rail"] for r in body["rails"]] == ["joint-pain", "hrv-floor"]
    assert body["analysis_withheld_by"] == ["joint-pain"]
    assert body["plan_vs_execution"] is None
    assert [q["text"] for q in body["questions"]] == [overshoot_text()]


def test_json_rows_on_a_quiet_day():
    view = build_day(ATHLETE, DayData(DAY), SETTINGS, plans())
    with client_for(lambda d: view) as c:
        body = c.get(f"/day/{DAY}.json").json()
    (row,) = body["plan_vs_execution"]
    assert row["planned"]["title"] == "Sweet spot 3x12" and row["planned"]["date"] == "2026-09-09"
    assert row["executed"]["np_w"] == 290.0 and row["status"] == "paired"
    assert row["work_hr_pct"] == pytest.approx(84.2, abs=0.1)
    assert row["questions"] == [overshoot_text()]


def test_day_without_date_redirects_to_today_and_the_provider_gets_the_date():
    seen = []

    def view_for(d):
        seen.append(d)
        return build_day(ATHLETE, DayData(d), SETTINGS, MemoryPlanStore())

    with client_for(view_for, today=lambda: date(2026, 10, 3)) as c:
        r = c.get("/day", follow_redirects=False)
        assert r.status_code in {302, 307} and r.headers["location"] == "/day/2026-10-03"
        assert "Day 2026-10-03" in c.get("/day").text
    assert seen == [date(2026, 10, 3)]


def test_bad_date_is_rejected():
    with client_for(lambda d: pytest.fail("not reached")) as c:
        assert c.get("/day/not-a-date").status_code == 422
