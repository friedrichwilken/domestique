from datetime import date, datetime
from pathlib import Path

import pytest

from domestique import config
from domestique.analysis.__main__ import format_report, run
from domestique.analysis.plan_vs_execution import DEFAULT_MARGIN_PP, questions_of
from domestique.ingest.icu_plan import ingest_planned
from domestique.ingest.plan_store import ExecutedSession, MemoryPlanStore, WorkInterval

DAY = date(2026, 9, 9)
PLAN = {
    "id": 2,
    "category": "WORKOUT",
    "start_date_local": "2026-09-09T18:00:00",
    "name": "Sweet spot 3x12",
    "description": "Sweet spot blocks, ca. 75% HFmax",
    "type": "Ride",
}


class FakeEvents:
    athlete_id = "iTest"

    def events(self, oldest, newest):
        return [PLAN]


def store_with(work_hr: float) -> MemoryPlanStore:
    store = MemoryPlanStore()
    ride = ExecutedSession(
        12, "Ride", datetime(2026, 9, 9, 18, 5), 290.0, 150.0, 182.0, 0.82,
        (WorkInterval(720, work_hr),),
    )  # fmt: skip
    store.add_activity("iTest", ride)
    ingest_planned(store, FakeEvents(), DAY, DAY)
    return store


def load(tmp_path: Path, extra: str = "") -> config.Config:
    (tmp_path / "config.yaml").write_text(
        f"athlete_id: iTest\ntimezone: UTC\nbedtime: '22:00'\nhr_max: 190\n{extra}"
    )
    return config.load({"DOMESTIQUE_HOME": str(tmp_path)})


def test_margin_defaults_when_absent(tmp_path):
    cfg = load(tmp_path)
    assert cfg.overshoot_margin_pp == DEFAULT_MARGIN_PP
    # 160 bpm of 190 = 84% against ~75%: inside the default 10 pp
    assert questions_of(run(cfg, store_with(160.0), DAY)) == []


def test_margin_from_config_overrides_the_default(tmp_path):
    cfg = load(tmp_path, "overshoot_margin_pp: 5\n")
    assert cfg.overshoot_margin_pp == 5.0
    (q,) = questions_of(run(cfg, store_with(160.0), DAY))
    assert q.context["margin_pp"] == 5.0


def test_margin_must_be_a_number(tmp_path):
    with pytest.raises(TypeError, match="overshoot_margin_pp"):
        load(tmp_path, "overshoot_margin_pp: lots\n")


def test_report_lists_rows_then_questions(tmp_path):
    cfg = load(tmp_path, "overshoot_margin_pp: 5\n")
    lines = format_report(run(cfg, store_with(160.0), DAY))
    assert lines[0].startswith("Sweet spot 3x12: prescribed 75% HFmax | paired: NP 290 W")
    assert "work HR 84% of max" in lines[0]
    assert lines[1].startswith("question: On 2026-09-09")
    assert format_report([]) == ["no planned session"]
