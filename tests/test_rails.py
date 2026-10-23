import re
from datetime import date
from pathlib import Path

import pytest

from domestique.intent import load_intent
from domestique.rails import (
    DEFAULT_LIMITS,
    RAILS,
    DayData,
    Limits,
    evaluate,
    hrv_floor,
    illness,
    joint_pain,
    limits_from_intent,
    ramp_ceiling,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BASELINES = {"hrv": 80.0, "rhr": 50.0}
D = date(2026, 9, 9)
QUIET = DayData(
    D, subjective_tags=("legs-heavy",), hrv=78, ctl_delta_7d=4.0, context_kinds=("work",)
)

# A rail's wording refers; it never prescribes training.
ADVICE = re.compile(
    r"\b(ride|riding|spin|easy|rest|stretch|zone|watts|recovery|train|session|minutes?)\b", re.I
)


@pytest.mark.parametrize(
    ("rail", "day", "action"),
    [
        (joint_pain, DayData(D, subjective_tags=("joint-pain",)), "stop_plan"),
        (hrv_floor, DayData(D, hrv=50), "downgrade_day"),
        (ramp_ceiling, DayData(D, ctl_delta_7d=8.5), "refuse_additional_load"),
        (illness, DayData(D, context_kinds=("illness",)), "no_intensity"),
    ],
)
def test_rail_triggers(rail, day, action):
    result = rail(day, BASELINES)
    assert result is not None
    assert result.action == action
    assert not ADVICE.search(result.wording)


@pytest.mark.parametrize("rail", list(RAILS.values()))
def test_rail_quiet(rail):
    assert rail(QUIET, BASELINES, DEFAULT_LIMITS) is None


def test_joint_pain_refers_to_physio_or_surgeon():
    result = joint_pain(DayData(D, subjective_tags=("joint-pain",)), BASELINES)
    assert result is not None
    assert "physio or surgeon" in result.wording


def test_hrv_floor_edges():
    assert hrv_floor(DayData(D, hrv=52), BASELINES) is None  # exactly 65% of 80
    assert hrv_floor(DayData(D, hrv=51.9), BASELINES) is not None
    assert hrv_floor(DayData(D, hrv=10), {}) is None  # no baseline configured
    assert hrv_floor(DayData(D), BASELINES) is None  # no reading


def test_ramp_ceiling_edge():
    assert ramp_ceiling(DayData(D, ctl_delta_7d=7.0), BASELINES) is None
    assert ramp_ceiling(DayData(D, ctl_delta_7d=7.1), BASELINES) is not None


def test_quiet_day_evaluates_to_nothing():
    assert evaluate(QUIET, BASELINES) == []


def test_evaluate_collects_every_triggered_rail():
    day = DayData(D, subjective_tags=("joint-pain",), hrv=40, context_kinds=("illness",))
    assert [r.rail for r in evaluate(day, BASELINES)] == ["joint-pain", "hrv-floor", "illness"]


def test_limits_from_example_rails_and_override():
    rails = load_intent(EXAMPLES / "intent").rails
    assert limits_from_intent(rails) == Limits(hrv_floor_ratio=0.65, ramp_ceiling_ctl_7d=7.0)
    strict = Limits(hrv_floor_ratio=0.8)
    assert hrv_floor(DayData(D, hrv=60), BASELINES, strict) is not None
