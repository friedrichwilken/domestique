from datetime import datetime, time

import pytest

from domestique.metrics import (
    decoupling_pct,
    efficiency_factor,
    hours_before_bed,
    interval_lr_balance,
    lr_balance,
    normalized_power,
    watts_at_hr_band,
)


def test_decoupling_steady_ride_is_about_one_percent(endurance):
    assert decoupling_pct(endurance["samples"]) == pytest.approx(1.0, abs=0.1)


def test_decoupling_zero_when_flat():
    s = [{"t_s": i, "watts": 200, "hr": 140} for i in range(100)]
    assert decoupling_pct(s) == pytest.approx(0.0)


def test_decoupling_negative_when_hr_falls():
    s = [{"t_s": i, "watts": 200, "hr": 140 if i < 50 else 130} for i in range(100)]
    assert decoupling_pct(s) < 0


def test_decoupling_needs_data():
    assert decoupling_pct([]) is None
    assert decoupling_pct([{"t_s": 0, "watts": 200, "hr": 0}]) is None


def test_normalized_power_constant_equals_power():
    s = [{"t_s": i, "watts": 250} for i in range(120)]
    assert normalized_power(s) == pytest.approx(250)
    assert normalized_power(s[:10]) is None


def test_normalized_power_exceeds_average_when_variable(intervals):
    watts = [s["watts"] for s in intervals["samples"]]
    assert normalized_power(intervals["samples"]) > sum(watts) / len(watts)


def test_efficiency_factor_steady_ride(endurance):
    # NP ~200 W over mean HR ~130.7 bpm
    assert efficiency_factor(endurance["samples"]) == pytest.approx(1.53, abs=0.03)


def test_lr_balance_per_interval_shifts_63_to_59(intervals):
    per = interval_lr_balance(intervals["samples"], intervals["intervals"])
    assert len(per) == 6
    assert per[0] == pytest.approx(63.0, abs=0.01)
    assert per[-1] == pytest.approx(59.0, abs=0.01)
    assert per == sorted(per, reverse=True)
    for got, iv in zip(per, intervals["intervals"], strict=True):
        assert got == pytest.approx(iv["expected_lr"], abs=0.01)


def test_lr_balance_whole_ride_between_rest_and_reps(intervals, endurance):
    assert 50 < lr_balance(intervals["samples"]) < 63
    assert lr_balance(endurance["samples"]) == pytest.approx(50.0)
    assert lr_balance([{"t_s": 0, "lr": None}]) is None


def test_watts_at_hr_band(intervals):
    # reps have HR 160..175 at 330 W; nothing else is above 150
    assert watts_at_hr_band(intervals["samples"], 160, 175) == pytest.approx(330)
    assert watts_at_hr_band(intervals["samples"], 200, 210) is None


def test_hours_before_bed_same_day():
    assert hours_before_bed(datetime(2026, 9, 8, 18, 30), time(22, 0)) == pytest.approx(3.5)


def test_hours_before_bed_rolls_to_next_day():
    assert hours_before_bed(datetime(2026, 9, 8, 22, 30), time(22, 0)) == pytest.approx(23.5)


def test_hours_before_bed_at_bedtime_is_zero():
    assert hours_before_bed(datetime(2026, 9, 8, 22, 0), time(22, 0)) == 0
