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


def mk(layer=SourceLayer.OBSERVED, conf=0.5, status=Status.ACTIVE, streak=0,
       horizon=Horizon.DAY, **kw):
    return Claim("c1", "a", "t", layer, horizon, conf, status, "x", datetime.now(UTC),
                 hit_streak=streak, **kw)


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


def test_eleventh_hit_flags_and_leaves_confidence():
    c = mk(conf=0.5, scored=10, hits=10)
    c2, notes = adjust_with_notes(c, True)
    assert c2.always_hit
    assert c2.confidence == 0.5
    assert (c2.scored, c2.hits) == (11, 11)
    assert len(notes) == 1 and "always-hit" in notes[0]


def test_flag_needs_ten_scored_and_over_95_percent():
    assert not adjust_with_notes(mk(scored=9, hits=9), True)[0].always_hit
    c, _ = adjust_with_notes(mk(scored=20, hits=19), True)  # 95% exactly: not above
    assert not c.always_hit and c.confidence == pytest.approx(0.6)


def test_flagged_claim_ignores_hits_but_not_misses_until_cleared():
    s = MemoryStore()
    c = s.propose_claim("a", "x", "observed", "day", [], "t", confidence=0.5)
    c = s.confirm_or_retire(c.id, "active", "ok", "human")
    c = replace(s.record_adjustment(replace(c, scored=10, hits=10), "seed", "t"))
    c, notes = adjust_with_notes(c, True)
    c = s.record_adjustment(c, "hit 11", "score", notes)
    assert c.always_hit and c.confidence == 0.5
    c, notes = adjust_with_notes(c, True)
    assert notes == [] and c.confidence == 0.5
    c, _ = adjust_with_notes(c, False)
    assert c.confidence == pytest.approx(0.35)
    c = s.record_adjustment(c, "miss", "score")
    c = s.clear_always_hit(c.id, "ranges tightened", "human")
    assert not c.always_hit
    assert adjust_confidence(c, True).confidence == pytest.approx(0.45)
    assert any("flag set" in h.reason for h in s.history(c.id))
    assert "cleared" in s.history(c.id)[-1].reason
