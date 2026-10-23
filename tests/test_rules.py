from dataclasses import replace
from datetime import UTC, datetime

import pytest

from domestique.claims.rules import (
    Horizon,
    SourceLayer,
    Status,
    adjust_confidence,
    adjust_with_notes,
)
from domestique.claims.store import Claim, MemoryStore


def mk(
    layer=SourceLayer.OBSERVED, conf=0.5, status=Status.ACTIVE, streak=0, horizon=Horizon.DAY, **kw
):
    return Claim(
        "c1",
        "a",
        "t",
        layer,
        horizon,
        conf,
        status,
        "x",
        datetime.now(UTC),
        hit_streak=streak,
        **kw,
    )


def test_hit_raises_and_caps():
    assert adjust_confidence(mk(conf=0.5), True).confidence == pytest.approx(0.6)
    assert adjust_confidence(mk(conf=0.9), True).confidence == 0.95


def test_miss_lowers_and_floors():
    c = adjust_confidence(mk(conf=0.5, streak=3), False)
    assert c.confidence == pytest.approx(0.35)
    assert c.hit_streak == 0
    assert adjust_confidence(mk(conf=0.2), False).confidence == pytest.approx(0.05)


def test_prior_promoted_after_five_consecutive_hits():
    c = mk(SourceLayer.PRIOR, 0.4)
    for i in range(4):
        c = adjust_confidence(c, True)
        assert c.source_layer == SourceLayer.PRIOR, i
    c = adjust_confidence(c, True)
    assert c.source_layer == SourceLayer.OBSERVED


def test_miss_resets_promotion_streak():
    c = mk(SourceLayer.PRIOR, 0.4)
    for _ in range(4):
        c = adjust_confidence(c, True)
    c = adjust_confidence(c, False)
    c = adjust_confidence(c, True)
    assert c.source_layer == SourceLayer.PRIOR


def test_non_observed_capped_below_high_confidence():
    c = mk(SourceLayer.STATED, 0.7)
    assert adjust_confidence(c, True).confidence == 0.7


def test_low_confidence_retires():
    c = adjust_confidence(mk(conf=0.2), False)  # 0.05 < 0.1
    assert c.status == Status.RETIRED
    assert adjust_confidence(mk(conf=0.3), False).status == Status.ACTIVE


def test_retired_claim_not_adjusted():
    c = mk(status=Status.RETIRED, conf=0.3)
    assert adjust_confidence(c, True) == c


def test_miss_lowers_confidence_in_store_with_history():
    s = MemoryStore()
    c = s.propose_claim("a", "x", "observed", "day", [], "t", confidence=0.6)
    c = s.confirm_or_retire(c.id, "active", "ok", "human")
    c = s.record_adjustment(adjust_confidence(c, False), "miss", "score")
    assert c.confidence == pytest.approx(0.45)
    assert [h.reason for h in s.history(c.id)] == ["proposed", "ok", "miss"]


def test_retired_claim_never_feeds_prediction():
    s = MemoryStore()
    a = s.propose_claim("a", "x", "prior", "day", [], "t")
    b = s.propose_claim("a", "y", "prior", "day", [], "t")
    s.confirm_or_retire(a.id, "active", "ok", "human")
    s.confirm_or_retire(b.id, "active", "ok", "human")
    s.confirm_or_retire(b.id, "retired", "missed", "human")
    assert [c.id for c in s.query_claims(athlete_id="a", status="active")] == [a.id]
    assert replace(b, status=Status.RETIRED).status == Status.RETIRED


def test_season_prior_never_promoted_and_refusal_logged():
    s = MemoryStore()
    c = s.propose_claim("a", "x", "prior", "season", [], "t", confidence=0.4)
    c = s.confirm_or_retire(c.id, "active", "ok", "human")
    for i in range(1, 8):
        c, notes = adjust_with_notes(c, True)
        c = s.record_adjustment(c, f"hit {i}", "score", notes)
        assert c.source_layer == SourceLayer.PRIOR
        assert c.confidence <= 0.5
    assert c.confidence == 0.5
    refused = [h for h in s.history(c.id) if "promotion refused" in h.reason]
    assert len(refused) == 1


def test_week_prior_promoted_with_cap():
    c = mk(SourceLayer.PRIOR, 0.4, horizon=Horizon.WEEK)
    for _ in range(5):
        c = adjust_confidence(c, True)
    assert c.source_layer == SourceLayer.OBSERVED
    assert c.confidence <= 0.7
    for _ in range(5):
        c = adjust_confidence(c, True)
    assert c.confidence == 0.7


def test_day_observed_reaches_layer_cap():
    c = mk(conf=0.9, horizon=Horizon.DAY)
    assert adjust_confidence(c, True).confidence == 0.95


def test_season_cap_applies_to_any_layer():
    c = mk(SourceLayer.OBSERVED, 0.9, horizon=Horizon.SEASON)
    assert adjust_confidence(c, False).confidence == 0.5


def run(c, outcomes):
    """Apply ``(hit, abs_error, half_range)`` outcomes in order; return the claim and all notes."""
    notes = []
    for hit, err, half in outcomes:
        c, n = adjust_with_notes(c, hit, err, half)
        notes.extend(n)
    return c, notes


def test_wide_range_is_flagged_uninformative_and_further_hits_leave_confidence():
    # ten hits whose errors average a tenth of the half-range
    c, notes = run(mk(conf=0.3), [(True, 0.1, 1.0)] * 9)
    assert not c.uninformative and c.confidence == pytest.approx(0.95)
    c = replace(c, confidence=0.5)
    c, notes = run(c, [(True, 0.1, 1.0)])
    assert c.uninformative and not c.overconfident
    assert c.confidence == 0.5  # the tenth hit raised the flag and did not count
    assert len(notes) == 1 and "uninformative flag set" in notes[0]
    c, notes = run(c, [(True, 0.1, 1.0)] * 3)
    assert c.confidence == 0.5 and notes == []
    assert (c.scored, c.hits, c.calib_scored) == (13, 13, 13)


def test_well_calibrated_claim_carries_no_flag():
    # twelve predictions, eleven hits, errors averaging half the half-range
    outcomes = [(True, 0.5, 1.0)] * 5 + [(False, 0.5, 1.0)] + [(True, 0.5, 1.0)] * 6
    c, notes = run(mk(conf=0.5), outcomes)
    assert not c.uninformative and not c.overconfident and notes == []
    assert (c.calib_scored, c.calib_hits) == (12, 11)


def test_hit_rate_alone_never_flags():
    # ten straight hits used to raise the always-hit flag; a well-sized range hits that often
    c, notes = run(mk(conf=0.5), [(True, 0.6, 1.0)] * 10)
    assert not c.uninformative and notes == []
    assert c.confidence == 0.95


def test_overconfident_claim_flagged_and_loses_an_extra_miss_step():
    # ten scored predictions, five hits: the tenth outcome raises the flag
    outcomes = [(True, 0.5, 1.0), (False, 2.0, 1.0)] * 4 + [(True, 0.5, 1.0)]
    c, _ = run(mk(conf=0.5, horizon=Horizon.DAY), outcomes)
    assert not c.overconfident and c.calib_scored == 9
    before = replace(c, confidence=0.6)
    normal = adjust_confidence(replace(before, calib_scored=0, calib_hits=0), False, 2.0, 1.0)
    flagged, notes = adjust_with_notes(before, False, 2.0, 1.0)
    assert flagged.overconfident and not flagged.uninformative
    assert (flagged.calib_scored, flagged.calib_hits) == (10, 5)
    assert normal.confidence == pytest.approx(0.45)
    assert flagged.confidence == pytest.approx(0.30)  # one extra miss step
    assert len(notes) == 1 and "overconfident flag set" in notes[0]


def test_flags_need_ten_scored():
    c, notes = run(mk(conf=0.3), [(True, 0.01, 1.0)] * 9)
    assert not c.uninformative and notes == []
    c, _ = run(mk(conf=0.9), [(False, 2.0, 1.0)] * 9)
    assert not c.overconfident


def test_uninformative_claim_ignores_hits_but_not_misses_until_cleared():
    s = MemoryStore()
    c = s.propose_claim("a", "x", "observed", "day", [], "t", confidence=0.5)
    c = s.confirm_or_retire(c.id, "active", "ok", "human")
    seeded = replace(
        c, scored=9, hits=9, calib_scored=9, calib_hits=9, calib_abs_error=0.9, calib_half_range=9.0
    )
    c = s.record_adjustment(seeded, "seed", "t")
    c, notes = adjust_with_notes(c, True, 0.1, 1.0)
    c = s.record_adjustment(c, "hit 10", "score", notes)
    assert c.uninformative and c.confidence == 0.5
    c, notes = adjust_with_notes(c, True, 0.1, 1.0)
    assert notes == [] and c.confidence == 0.5
    c, _ = adjust_with_notes(c, False, 2.0, 1.0)
    assert c.confidence == pytest.approx(0.35)
    c = s.record_adjustment(c, "miss", "score")
    c = s.clear_flags(c.id, "range narrowed", "human")
    assert not c.uninformative and not c.overconfident
    assert (c.calib_scored, c.calib_hits, c.calib_abs_error, c.calib_half_range) == (0, 0, 0, 0)
    assert c.scored == 12  # the lifetime count stays
    assert adjust_confidence(c, True, 0.1, 1.0).confidence == pytest.approx(0.45)
    assert any("uninformative flag set" in h.reason for h in s.history(c.id))
    assert "calibration flags cleared" in s.history(c.id)[-1].reason
