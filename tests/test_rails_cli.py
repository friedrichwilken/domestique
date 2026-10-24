from datetime import date

from domestique.rails import DayData, RailResult, evaluate
from domestique.rails.__main__ import QUIET, format_results

BASELINES = {"hrv": 80.0}


def test_quiet_day_prints_one_line():
    assert format_results([]) == [QUIET]


def test_one_line_per_result_with_rail_action_and_wording():
    fake = [
        RailResult(rail="hrv-floor", action="downgrade_day", wording="HRV is under the floor."),
        RailResult(rail="illness", action="no_intensity", wording="Illness is logged."),
    ]
    assert format_results(fake) == [
        "hrv-floor\tdowngrade_day\tHRV is under the floor.",
        "illness\tno_intensity\tIllness is logged.",
    ]


def test_formats_what_the_rails_return_for_a_fake_day():
    day = DayData(date(2026, 9, 9), subjective_tags=("joint-pain",), hrv=40.0)
    lines = format_results(evaluate(day, BASELINES))
    assert [line.split("\t")[:2] for line in lines] == [
        ["joint-pain", "stop_plan"],
        ["hrv-floor", "downgrade_day"],
    ]
