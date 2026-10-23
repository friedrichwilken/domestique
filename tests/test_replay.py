"""Replay eval over the fixture season (change replay-eval, tasks 1.1 and 2.1-2.5)."""

import importlib.util
import json
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean

import pytest
import yaml

from domestique.claims.seed import SeedBinding, SeedClaim, read_seed
from domestique.loop.model import Metric
from domestique.replay.bootstrap import ReviewEntry, enforce_season_rule, review_document
from domestique.replay.fixture import FixtureSeason
from domestique.replay.harness import evening_intensity, history_for, run_replay
from domestique.replay.report import (
    SEGMENT_EVENING,
    planted_effect,
    select,
    summary_markdown,
    weekly_rows,
)
from domestique.replay.run import main
from domestique.replay.source import CursorView

ROOT = Path(__file__).resolve().parents[1]
SEASON = ROOT / "evals/fixtures/season_a"
PRIORS = ROOT / "evals/priors.yaml"
FILES = ("meta.json", "planned.json", "activities.json", "wellness.json")
PLANTED_HOUR = 1.0  # the fixture's sleep cost of evening intensity


@pytest.fixture(scope="module")
def season():
    return FixtureSeason(SEASON)


@pytest.fixture(scope="module")
def priors():
    return read_seed(PRIORS)


@pytest.fixture(scope="module")
def loop_on(season, priors):
    return run_replay(season, priors, loop_on=True)


@pytest.fixture(scope="module")
def loop_off(season, priors):
    return run_replay(season, priors, loop_on=False)


def _generator():
    spec = importlib.util.spec_from_file_location("season_a_generate", SEASON / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module while the file executes
    spec.loader.exec_module(mod)
    return mod


# --- 1.1 fixture season --------------------------------------------------------


def test_regeneration_is_byte_identical(tmp_path):
    _generator().write(tmp_path)
    for name in FILES:
        assert (tmp_path / name).read_bytes() == (SEASON / name).read_bytes(), name


def test_fixture_season_is_twelve_weeks_with_the_planted_effect(season):
    assert (season.last - season.first).days + 1 == 84
    wellness = {r["date"]: r for r in json.loads((SEASON / "wellness.json").read_text())}
    after_evening, other = [], []
    day = season.first
    while day <= season.last:
        (session,) = season.planned_on(day) or (None,)
        sleep = wellness[(day + timedelta(days=1)).isoformat()]["sleep_s"] / 3600
        ridden = session is not None and session.paired_activity_id is not None
        (after_evening if ridden and evening_intensity(session) else other).append(sleep)
        day += timedelta(days=1)
    assert len(after_evening) >= 12
    assert 0.7 < fmean(other) - fmean(after_evening) < 1.3  # about one hour


# --- 2.1 cursor ----------------------------------------------------------------


def test_peek_attempt_returns_nothing(season):
    cursor = date(2026, 2, 3)
    view = CursorView(season, cursor)
    assert view.night(cursor + timedelta(days=1)) is None
    assert view.night(cursor) is not None  # this morning's reading is visible
    assert all(n.date <= cursor for n in view.nights(cursor - timedelta(days=5), date(2026, 3, 29)))
    assert all(r.start_local.date() < cursor for r in view.rides(season.first, season.last))
    assert view.planned_on(cursor + timedelta(days=1)) == []
    (today,) = view.planned_on(cursor)
    future_ride = season.planned_on(cursor)[0].paired_activity_id
    assert future_ride is not None and today.paired_activity_id is None  # ridden later today
    assert view.ride(future_ride) is None and view.samples(future_ride) == []
    later = CursorView(season, cursor + timedelta(days=1))
    assert later.ride(future_ride) is not None and later.samples(future_ride)


def test_history_never_reaches_the_session_day(season):
    day = season.first
    while day <= season.last:
        view = CursorView(season, day)
        for session in view.planned_on(day):
            history = history_for(view, session)
            ids = {r.activity_id for r in history.rides}
            assert all(season.ride(i).start_local.date() < day for i in ids)
            assert len(history.sleep_h) <= (day - season.first).days + 1
        day += timedelta(days=1)


# --- 2.2 output ----------------------------------------------------------------


def test_headline_is_the_last_line(tmp_path, capsys):
    written = main(["--out", str(tmp_path)], repo=ROOT)
    summary = (tmp_path / "summary.md").read_text().splitlines()
    assert summary[-1].startswith("Headline: mean absolute error across metrics, final 4 weeks:")
    printed = capsys.readouterr().out.strip().splitlines()
    assert printed[-1] == summary[-1]
    rows = (tmp_path / "weekly.csv").read_text().splitlines()
    assert rows[0] == "week,week_start,metric,segment,n,mean_error,mae,mae_pct,hit_rate"
    assert {r.split(",")[0] for r in rows[1:]} == {str(w) for w in range(1, 13)}
    assert {r.split(",")[2] for r in rows[1:]} == {m.value for m in Metric}
    assert written.result.loop_on and (tmp_path / "review.yaml").exists()


def test_weekly_rows_carry_signed_error_and_hit_rate(loop_on):
    rows = weekly_rows(loop_on)
    assert any(float(r["mean_error"]) < 0 for r in rows)
    assert all(0.0 <= float(r["hit_rate"]) <= 1.0 for r in rows)


# --- 2.3 loop on/off -----------------------------------------------------------


def test_planted_effect_holds_on_the_committed_seed_with_the_loop_on(loop_on, loop_off):
    on, off = planted_effect(loop_on), planted_effect(loop_off)
    # without the loop the planted hour is never learned: the error stays
    assert off.second.mae > 0.8 * off.first.mae
    # with it, the second half is under half the loop-off error and under a third of the hour.
    # Shadow scoring lets the rival take over within the first evening sessions, so the first
    # half is already close to the noise floor; a first-half/second-half ratio no longer
    # measures learning (see the loop-calibration PR).
    assert on.second.mae < 0.5 * off.second.mae
    assert on.second.mae < PLANTED_HOUR / 3
    assert on.first.mae < off.first.mae
    evening = next(c for c in loop_on.claims if c.text.startswith("Intensity in the evening"))
    late = select(loop_on, Metric.SLEEP_HOURS, SEGMENT_EVENING, range(7, 13))
    assert late and all(s.prediction.claim_id == evening.id for s in late)


def test_rivals_are_shadow_scored_and_reported_apart(loop_on):
    assert loop_on.shadow_scored
    assert all(not s.prediction.official for s in loop_on.shadow_scored)
    assert all(s.prediction.official for s in loop_on.scored)
    assert loop_on.shadows == len(loop_on.shadow_scored)


def test_report_lists_both_flags_per_claim(season, priors, tmp_path):
    wide = SeedClaim(
        text="Peak heart rate lands within 30 bpm of the band top (test only).",
        source_layer="prior",
        horizon="day",
        confidence=0.5,
        evidence=(),
        bindings=(SeedBinding("peak_hr", {"offset": 5, "range_abs": 30}, {}),),
    )
    seed = replace(
        priors, claims=(wide, *(c for c in priors.claims if not c.text.startswith("Peak")))
    )
    result = run_replay(season, seed, loop_on=True)
    flagged = next(c for c in result.claims if c.text == wide.text)
    assert flagged.uninformative and not flagged.overconfident
    summary = summary_markdown(result, "fixture")
    assert "| uninformative | overconfident |" in summary
    rows = [line for line in summary.splitlines() if line.startswith(f"| {wide.text}")]
    assert len(rows) == 1 and rows[0].endswith("| yes | no |")
    claim_rows = [
        line for line in summary.split("## Claims at the end")[1].splitlines() if line[:2] == "| "
    ]
    assert len(claim_rows) == len(result.claims) + 1  # plus the header
    doc = review_document(result, "fixture")
    entry = next(c for c in doc["candidates"] if c["text"] == wide.text)
    assert any("uninformative flag" in n for n in entry["notes"])


def test_loop_off_moves_no_confidence(loop_off, priors):
    assert [c.confidence for c in loop_off.claims] == [c.confidence for c in priors.claims]
    assert all(c.scored == 0 for c in loop_off.claims)


def test_replay_is_deterministic(season, priors, loop_on):
    again = run_replay(season, priors, loop_on=True)
    assert [(s.prediction.metric, s.outcome.actual, s.outcome.error) for s in again.scored] == [
        (s.prediction.metric, s.outcome.actual, s.outcome.error) for s in loop_on.scored
    ]


# --- 2.5 bootstrap -------------------------------------------------------------


def test_bootstrap_review_lists_candidates_and_writes_no_active_claim(loop_on, tmp_path):
    main(["--out", str(tmp_path)], repo=ROOT)
    doc = yaml.safe_load((tmp_path / "review.yaml").read_text())
    assert doc["candidates"]
    for entry in doc["candidates"]:
        assert entry["status"] == "candidate"
        assert entry["horizon"] in {"day", "week", "season"}
        assert 0.0 <= entry["hit_rate"] <= 1.0 and entry["confidence"] > 0
        assert any(e["kind"] in {"activity", "wellness"} for e in entry["evidence"])
    evening = next(c for c in doc["candidates"] if c["text"].startswith("Intensity in the evening"))
    assert evening["proposal"] == "promote" and evening["source_layer"] == "observed"
    # the working store holds the seeded priors only: nothing new became active
    active = {c.id for c in loop_on.claims if c.status == "active"}
    assert active <= set(loop_on.seeded)
    assert len(loop_on.claims) == len(loop_on.seeded)


def test_bootstrap_proposes_a_pattern_from_consistent_misses(loop_off):
    doc = review_document(loop_off, "fixture")
    (pattern,) = [
        c
        for c in doc["candidates"]
        if c["origin"] == "pattern" and c["bindings"][0]["metric"] == "sleep_hours"
    ]
    assert pattern["source_layer"] == "observed" and pattern["horizon"] == "day"
    assert pattern["bindings"][0]["conditions"]["start_hour_from"] == 17
    assert -1.2 < pattern["bindings"][0]["params"]["offset"] < -0.6
    assert pattern["hit_rate_basis"] == "in-sample"


def test_no_season_claim_outside_the_prior_layer(season, priors):
    always_right = SeedClaim(
        text="Season prior bound to peak heart rate (test only).",
        source_layer="prior",
        horizon="season",
        confidence=0.5,
        evidence=(),
        bindings=(SeedBinding("peak_hr", {"offset": 6, "range_abs": 6}, {}),),
    )
    seed = replace(
        priors,
        claims=(*(c for c in priors.claims if not c.text.startswith("Peak")), always_right),
    )
    result = run_replay(season, seed, loop_on=True)
    tested = next(c for c in result.claims if c.text == always_right.text)
    assert tested.hits >= 5 and tested.source_layer == "prior"
    doc = review_document(result, "fixture")
    assert all(c["source_layer"] == "prior" for c in doc["candidates"] if c["horizon"] == "season")
    assert any(c["horizon"] == "season" for c in doc["candidates"])


def test_season_rule_demotes_whatever_produced_an_observed_season_entry():
    entry = ReviewEntry(
        origin="pattern",
        proposal="new",
        text="x",
        source_layer="observed",
        horizon="season",
        confidence=0.3,
        scored=6,
        hits=6,
        hit_rate=1.0,
        hit_rate_basis="in-sample",
        bindings=(),
        evidence=(),
    )
    (fixed,) = enforce_season_rule([entry])
    assert fixed.source_layer == "prior" and fixed.proposal == "keep"
