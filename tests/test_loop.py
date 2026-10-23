"""Prediction and scoring loop over in-memory stores (tasks 3.1-3.3)."""

from dataclasses import replace
from datetime import date, datetime

import pytest

from domestique.analysis.plan_vs_execution import plan_vs_execution
from domestique.claims.store import MemoryStore
from domestique.ingest.icu_plan import ingest_planned
from domestique.ingest.plan_store import (
    ExecutedSession,
    MemoryPlanStore,
    PlannedSession,
    WorkInterval,
)
from domestique.loop.model import (
    Actuals,
    Binding,
    Conditions,
    History,
    Metric,
    RideSamples,
    parse_binding,
)
from domestique.loop.predict import applies, predict
from domestique.loop.score import overshoot_flag, score_session
from domestique.loop.store import MemoryLoopStore

ATHLETE = "athlete-synth-1"
HR_MAX = 190.0
DAY = date(2026, 9, 9)


def steady(watts, hr, n=600):
    return [{"t_s": float(t), "watts": watts, "hr": hr} for t in range(n)]


def planned(
    pid=1,
    description="Endurance, 60-70% of max heart rate",
    start="2026-09-09T18:00:00",
    planned_if=0.9,
    paired=None,
    title="Evening tempo",
):
    return PlannedSession(
        id=pid,
        date=DAY,
        start_local=datetime.fromisoformat(start) if start else None,
        sport="Ride",
        title=title,
        description=description,
        planned_tss=80.0,
        planned_if=planned_if,
        paired_activity_id=paired,
    )


def claim(store, layer="observed", confidence=0.5, status="active", horizon="day", text="c"):
    c = store.propose_claim(ATHLETE, text, layer, horizon, [], "test", confidence)
    if status != "candidate":
        c = store.confirm_or_retire(c.id, status, "test setup", "human")
    return c


HISTORY = History(
    hr_max=HR_MAX,
    baselines={"hrv": 80.0},
    rides=(
        RideSamples(103, steady(220.0, 125.0)),
        RideSamples(102, steady(210.0, 125.0)),
        RideSamples(101, steady(300.0, 160.0)),  # never in the 114-133 bpm band
        RideSamples(100, steady(200.0, 120.0)),
        RideSamples(99, steady(400.0, 125.0)),  # beyond the three most recent usable
    ),
    sleep_h=(7.0, 7.5, 8.0, 7.5, 7.0, 8.0, 7.5),
)


# --- 3.1 predict ---------------------------------------------------------------


def test_no_claim_metric_yields_no_prediction_and_a_reported_gap():
    claims = MemoryStore()
    c = claim(claims)
    bindings = [Binding(c.id, Metric.PEAK_HR, offset=10, range_abs=4)]
    result = predict(planned(), claims.query_claims(), bindings, HISTORY)
    assert [p.metric for p in result.predictions] == [Metric.PEAK_HR]
    assert {g.metric for g in result.gaps} == {
        Metric.WATTS_AT_HR,
        Metric.HRV_NEXT_MORNING,
        Metric.SLEEP_HOURS,
    }
    assert all("no active claim" in g.reason for g in result.gaps)


def test_peak_hr_from_prescribed_band_plus_claim_offset():
    claims = MemoryStore()
    c = claim(claims)
    bindings = [Binding(c.id, Metric.PEAK_HR, offset=10, range_abs=4)]
    (p,) = predict(planned(), claims.query_claims(), bindings, HISTORY).predictions
    # 70% of 190 = 133 bpm, plus 10
    assert (p.expected, p.low, p.high) == (143.0, 139.0, 147.0)
    assert p.claim_ids == (c.id,)


def test_watts_at_hr_from_last_three_rides_in_band_with_five_percent_range():
    claims = MemoryStore()
    c = claim(claims)
    bindings = [Binding(c.id, Metric.WATTS_AT_HR, range_pct=5, rides=3)]
    (p,) = predict(planned(), claims.query_claims(), bindings, HISTORY).predictions
    assert (p.expected, p.low, p.high) == (210.0, 199.5, 220.5)
    assert p.basis["rides"] == [103, 102, 100]
    assert (p.basis["hr_low"], p.basis["hr_high"]) == (114.0, 133.0)


def test_watts_at_hr_gap_when_too_few_rides_in_band():
    claims = MemoryStore()
    c = claim(claims)
    bindings = [Binding(c.id, Metric.WATTS_AT_HR, range_pct=5, rides=5)]
    result = predict(planned(), claims.query_claims(), bindings, HISTORY)
    assert result.predictions == ()
    gap = next(g for g in result.gaps if g.metric == Metric.WATTS_AT_HR)
    assert "only 4 of 5" in gap.reason


def test_no_guidance_in_description_is_a_gap_not_a_guess():
    claims = MemoryStore()
    c = claim(claims)
    bindings = [Binding(c.id, Metric.PEAK_HR, range_abs=4)]
    result = predict(
        planned(description="3x12 sweet spot"), claims.query_claims(), bindings, HISTORY
    )
    assert result.predictions == ()
    gap = next(g for g in result.gaps if g.metric == Metric.PEAK_HR)
    assert "no heart-rate guidance" in gap.reason


@pytest.mark.parametrize("status", ["retired", "candidate"])
def test_retired_and_candidate_claims_never_feed_predictions(status):
    claims = MemoryStore()
    c = claim(claims, status=status)
    bindings = [Binding(c.id, Metric.PEAK_HR, range_abs=4)]
    result = predict(planned(), claims.query_claims(), bindings, HISTORY)
    assert result.predictions == ()


def test_uninformative_claim_is_never_official_but_still_shadow_scored():
    claims = MemoryStore()
    c = claim(claims)
    flagged = replace(c, uninformative=True)
    result = predict(planned(), [flagged], [Binding(c.id, Metric.PEAK_HR, range_abs=4)], HISTORY)
    assert result.official == ()
    (shadow,) = result.predictions
    assert not shadow.official and shadow.claim_id == c.id
    gap = next(g for g in result.gaps if g.metric == Metric.PEAK_HR)
    assert "uninformative" in gap.reason


def test_hrv_claim_applies_by_session_type_and_time_of_day():
    claims = MemoryStore()
    c = claim(claims, text="HRV drops after evening intensity")
    evening_hard = Conditions(min_if=0.85, start_hour_from=17, start_hour_to=23)
    bindings = [
        Binding(c.id, Metric.HRV_NEXT_MORNING, change_pct=-10, range_pct=5, when=evening_hard)
    ]
    (p,) = predict(planned(), claims.query_claims(), bindings, HISTORY).predictions
    assert (p.expected, p.low, p.high) == (72.0, 68.4, 75.6)
    assert p.basis["baseline_from"] == "config"
    morning = predict(
        planned(start="2026-09-09T07:00:00"), claims.query_claims(), bindings, HISTORY
    )
    assert morning.predictions == ()
    easy = predict(planned(planned_if=0.6), claims.query_claims(), bindings, HISTORY)
    assert easy.predictions == ()
    untimed = predict(
        planned(start="2026-09-09T00:00:00"), claims.query_claims(), bindings, HISTORY
    )
    assert untimed.predictions == ()


def test_time_of_day_condition_wraps_past_midnight():
    late = Conditions(start_hour_from=22, start_hour_to=2)
    assert applies(late, planned(start="2026-09-09T23:00:00"))
    assert applies(late, planned(start="2026-09-09T01:00:00"))
    assert not applies(late, planned(start="2026-09-09T12:00:00"))


def test_sleep_baseline_from_recent_nights_when_not_configured():
    claims = MemoryStore()
    c = claim(claims)
    bindings = [Binding(c.id, Metric.SLEEP_HOURS, change_pct=-10, range_abs=0.5)]
    (p,) = predict(planned(), claims.query_claims(), bindings, HISTORY).predictions
    assert p.basis["base"] == 7.5 and p.expected == 6.75
    short = History(hr_max=HR_MAX, sleep_h=(7.0, 8.0))
    gap = predict(planned(), claims.query_claims(), bindings, short).gaps
    assert any("no baseline" in g.reason for g in gap)


def test_observed_beats_prior_and_the_prior_is_listed_as_superseded():
    claims = MemoryStore()
    prior = claim(claims, layer="prior", confidence=0.6)
    observed = claim(claims, layer="observed", confidence=0.3)
    bindings = [
        Binding(prior.id, Metric.PEAK_HR, offset=20, range_abs=4),
        Binding(observed.id, Metric.PEAK_HR, offset=5, range_abs=4),
    ]
    result = predict(planned(), claims.query_claims(), bindings, HISTORY)
    (p,) = result.official
    assert p.claim_ids == (observed.id,)
    assert p.basis["superseded"] == [prior.id]
    (shadow,) = (q for q in result.predictions if not q.official)
    assert shadow.claim_id == prior.id and shadow.expected == 153.0


def test_binding_parse_rejects_unknown_fields_and_zero_width_ranges():
    with pytest.raises(ValueError, match="unknown binding params"):
        parse_binding("x", "peak_hr", {"offset": 1, "range_abs": 2, "fudge": 1}, {})
    with pytest.raises(ValueError, match="unknown conditions"):
        parse_binding("x", "peak_hr", {"range_abs": 2}, {"weekday": "mon"})
    with pytest.raises(ValueError, match="zero-width"):
        parse_binding("x", "peak_hr", {"offset": 1}, {})
    b = parse_binding("x", "hrv_next_morning", {"range_pct": 5}, {"sports": ["Ride"]})
    assert b.when.sports == ("Ride",) and b.rides == 3


# --- 3.2 score -----------------------------------------------------------------


def setup_scoring(confidence=0.5, layer="observed"):
    claims = MemoryStore()
    c = claim(claims, layer=layer, confidence=confidence)
    loop = MemoryLoopStore()
    bindings = [Binding(c.id, Metric.PEAK_HR, offset=10, range_abs=4)]
    session = planned(paired=11)
    result = predict(session, claims.query_claims(), bindings, HISTORY)
    loop.save_predictions(result.predictions)
    return claims, loop, c, session


def ridden(max_hr, hrv=None, sleep=None):
    return Actuals(11, steady(210.0, 125.0), max_hr=max_hr, hrv_next_morning=hrv, sleep_hours=sleep)


def test_miss_lowers_confidence_with_a_history_row_naming_the_prediction():
    claims, loop, c, session = setup_scoring(confidence=0.5)
    result, applied = score_session(ATHLETE, session, loop, claims, ridden(170.0), None)
    (pred,) = loop.predictions.values()
    assert applied.outcomes == 1 and applied.adjustments == 1
    after = claims.query_claims()[0]
    assert after.confidence == 0.35
    assert pred.id in claims.history(c.id)[-1].reason
    assert loop.outcomes[pred.id].error == 27.0  # signed: actual 170 - expected 143
    assert result.outcomes[0].actual == 170.0


def test_hit_raises_confidence():
    claims, loop, _, session = setup_scoring(confidence=0.5)
    score_session(ATHLETE, session, loop, claims, ridden(145.0), None)
    assert claims.query_claims()[0].confidence == 0.6


def test_scored_once_when_the_job_runs_twice():
    claims, loop, c, session = setup_scoring(confidence=0.5)
    score_session(ATHLETE, session, loop, claims, ridden(170.0), None)
    rows_after_first = len(claims.history(c.id))
    _, again = score_session(ATHLETE, session, loop, claims, ridden(170.0), None)
    assert again.outcomes == 0 and again.adjustments == 0
    assert len(loop.outcomes) == 1
    assert len(claims.history(c.id)) == rows_after_first
    assert claims.query_claims()[0].confidence == 0.35


def test_missing_actuals_stay_pending_and_are_scored_on_a_later_run():
    claims = MemoryStore()
    c = claim(claims)
    loop = MemoryLoopStore()
    bindings = [
        Binding(c.id, Metric.PEAK_HR, offset=10, range_abs=4),
        Binding(c.id, Metric.HRV_NEXT_MORNING, change_pct=-10, range_pct=5),
    ]
    session = planned(paired=11)
    loop.save_predictions(predict(session, claims.query_claims(), bindings, HISTORY).predictions)
    first, _ = score_session(ATHLETE, session, loop, claims, ridden(145.0), None)
    assert [p.metric for p in first.pending] == [Metric.HRV_NEXT_MORNING]
    second, applied = score_session(ATHLETE, session, loop, claims, ridden(145.0, hrv=71.0), None)
    assert applied.outcomes == 1 and second.pending == ()
    assert len(loop.outcomes) == 2
    # one hit per run on the same claim: 0.5 -> 0.6 -> 0.7
    assert claims.query_claims()[0].confidence == 0.7


def test_unridden_session_scores_nothing():
    claims, loop, _, session = setup_scoring()
    result, applied = score_session(
        ATHLETE, session, loop, claims, Actuals(None, hrv_next_morning=70.0), None
    )
    assert applied.outcomes == 0
    assert result.pending[0].reason == "session was not ridden"


def test_predictions_are_pre_registered_once_per_session_and_metric():
    claims, loop, c, session = setup_scoring()
    again = predict(
        session, claims.query_claims(), [Binding(c.id, Metric.PEAK_HR, range_abs=1)], HISTORY
    )
    assert loop.save_predictions(again.predictions) == []
    assert len(loop.predictions) == 1


# --- loop-calibration 1.1 / 1.2: shadow scoring --------------------------------


def two_sleep_claims(claims, official_conf=0.5, rival_conf=0.4):
    """Two claims on sleep hours: the official one says no change, the rival says -1 h."""
    official = claim(claims, confidence=official_conf, text="sleep stays")
    rival = claim(claims, confidence=rival_conf, text="sleep drops an hour")
    bindings = [
        Binding(official.id, Metric.SLEEP_HOURS, range_abs=0.3),
        Binding(rival.id, Metric.SLEEP_HOURS, offset=-1.0, range_abs=0.3),
    ]
    return official, rival, bindings


def test_reported_prediction_is_the_official_one():
    claims, loop = MemoryStore(), MemoryLoopStore()
    official, rival, bindings = two_sleep_claims(claims)
    session = planned(paired=11)
    result = predict(session, claims.query_claims(), bindings, HISTORY)
    loop.save_predictions(result.predictions)
    listed = loop.predictions_for(session.id)
    assert len(listed) == 2
    (reported,) = (p for p in listed if p.official)
    (shadow,) = (p for p in listed if not p.official)
    assert reported.claim_id == official.id and shadow.claim_id == rival.id
    assert reported.basis["superseded"] == [rival.id]
    assert "superseded" not in shadow.basis
    # one official per metric: re-predicting keeps the first registration
    assert loop.save_predictions(result.predictions) == []
    assert describe_roles(predict(session, claims.query_claims(), bindings, HISTORY)) == {
        (official.id, True),
        (rival.id, False),
    }


def describe_roles(result):
    return {(p.claim_id, p.official) for p in result.predictions}


def test_late_official_prediction_is_kept_as_a_shadow():
    claims, loop = MemoryStore(), MemoryLoopStore()
    official, rival, bindings = two_sleep_claims(claims)
    session = planned(paired=11)
    first = predict(session, claims.query_claims(), bindings[:1], HISTORY)
    loop.save_predictions(first.predictions)
    # the rival's binding arrives later and it now outranks the first claim
    boosted = [replace(c, confidence=0.6) if c.id == rival.id else c for c in claims.query_claims()]
    second = predict(session, boosted, bindings, HISTORY)
    (saved,) = loop.save_predictions(second.predictions)
    assert saved.claim_id == rival.id and not saved.official
    assert [p.claim_id for p in loop.predictions_for(session.id) if p.official] == [official.id]


def test_rival_takes_over_after_the_official_claim_misses_four_times():
    claims, loop = MemoryStore(), MemoryLoopStore()
    # far enough apart that the official claim stays official through three misses
    official, rival, bindings = two_sleep_claims(claims, official_conf=0.95, rival_conf=0.15)
    for i in range(4):
        session = planned(pid=100 + i, paired=11)
        result = predict(session, claims.query_claims(status="active"), bindings, HISTORY)
        (reported,) = result.official
        assert reported.claim_id == official.id, i
        loop.save_predictions(result.predictions)
        # sleep baseline 7.5 h; the night came in an hour short: official misses, shadow hits
        actuals = ridden(150.0, sleep=6.5)
        _, applied = score_session(ATHLETE, session, loop, claims, actuals, None)
        assert applied.outcomes == 2 and applied.adjustments >= 1
    by_id = {c.id: c for c in claims.query_claims()}
    assert by_id[rival.id].confidence > by_id[official.id].confidence
    assert by_id[rival.id].hits == 4 and by_id[official.id].hits == 0
    nxt = planned(pid=200, paired=11)
    (reported,) = predict(nxt, claims.query_claims(status="active"), bindings, HISTORY).official
    assert reported.claim_id == rival.id


def test_shadow_misses_are_not_put_to_the_athlete_on_overshoot():
    rows, session = overshoot_rows(work_hr=171.0)
    flag = overshoot_flag(rows, session.id)
    claims, loop = MemoryStore(), MemoryLoopStore()
    good = claim(claims, confidence=0.5, text="peak runs 10 above the band")
    bad = claim(claims, layer="prior", confidence=0.5, text="peak runs 40 above the band")
    bindings = [
        Binding(good.id, Metric.PEAK_HR, offset=10, range_abs=4),
        Binding(bad.id, Metric.PEAK_HR, offset=40, range_abs=4),
    ]
    loop.save_predictions(predict(session, claims.query_claims(), bindings, HISTORY).predictions)
    _, applied = score_session(ATHLETE, session, loop, claims, ridden(144.0), flag)
    assert (applied.outcomes, applied.adjustments, applied.questions) == (2, 0, 0)


# --- 3.3 overshoot miss --------------------------------------------------------


class FakeEvents:
    athlete_id = ATHLETE

    def events(self, oldest, newest):
        return [
            {
                "id": 1,
                "category": "WORKOUT",
                "start_date_local": "2026-09-09T18:00:00",
                "name": "Endurance",
                "description": "Endurance, 60-70% of max heart rate",
                "type": "Ride",
            }
        ]


def overshoot_rows(work_hr):
    store = MemoryPlanStore()
    store.add_activity(
        ATHLETE,
        ExecutedSession(
            11,
            "Ride",
            datetime(2026, 9, 9, 18, 5),
            250.0,
            150.0,
            185.0,
            0.85,
            (WorkInterval(1800, work_hr),),
        ),
    )
    ingest_planned(store, FakeEvents(), DAY, DAY)
    rows = plan_vs_execution(store, ATHLETE, DAY, HR_MAX)
    return rows, rows[0].planned


def test_overshoot_miss_creates_a_question_and_leaves_claims_unchanged():
    rows, session = overshoot_rows(work_hr=171.0)  # 90% of max against 60-70%
    flag = overshoot_flag(rows, session.id)
    assert flag is not None
    claims = MemoryStore()
    c = claim(claims, confidence=0.5)
    loop = MemoryLoopStore()
    bindings = [Binding(c.id, Metric.PEAK_HR, offset=10, range_abs=4)]
    loop.save_predictions(predict(session, claims.query_claims(), bindings, HISTORY).predictions)
    history_before = len(claims.history(c.id))

    _, applied = score_session(ATHLETE, session, loop, claims, ridden(185.0), flag)

    assert applied.outcomes == 1 and applied.adjustments == 0 and applied.questions == 1
    assert claims.query_claims()[0].confidence == 0.5
    assert len(claims.history(c.id)) == history_before
    (q,) = loop.questions
    assert q.for_ == "athlete"
    assert q.context["kind"] == "prediction_loop.overshoot_miss"
    assert q.context["misses"][0]["metric"] == "peak_hr"
    assert q.context["misses"][0]["actual"] == 185.0
    assert "peak heart rate" in q.text and "intended" in q.text
    # a second run neither re-scores nor asks again
    _, again = score_session(ATHLETE, session, loop, claims, ridden(185.0), flag)
    assert again.questions == 0 and len(loop.questions) == 1


def test_overshoot_hit_asks_nothing_and_adjusts_nothing():
    rows, session = overshoot_rows(work_hr=171.0)
    flag = overshoot_flag(rows, session.id)
    claims = MemoryStore()
    c = claim(claims, confidence=0.5)
    loop = MemoryLoopStore()
    bindings = [Binding(c.id, Metric.PEAK_HR, offset=10, range_abs=4)]
    loop.save_predictions(predict(session, claims.query_claims(), bindings, HISTORY).predictions)
    _, applied = score_session(ATHLETE, session, loop, claims, ridden(144.0), flag)
    assert (applied.outcomes, applied.adjustments, applied.questions) == (1, 0, 0)
    assert claims.query_claims()[0].confidence == 0.5


def test_no_overshoot_flag_when_ridden_inside_guidance():
    rows, session = overshoot_rows(work_hr=128.0)
    assert overshoot_flag(rows, session.id) is None
