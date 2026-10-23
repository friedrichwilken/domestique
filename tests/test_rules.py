from dataclasses import replace
from datetime import UTC, datetime

import pytest

from domestique.claims.rules import SourceLayer, Status, adjust_confidence
from domestique.claims.store import Claim, MemoryStore


def mk(layer=SourceLayer.OBSERVED, conf=0.5, status=Status.ACTIVE, streak=0):
    return Claim("c1", "a", "t", layer, conf, status, "x", datetime.now(UTC), hit_streak=streak)


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
    c = s.propose_claim("a", "x", "observed", [], "t", confidence=0.6)
    c = s.confirm_or_retire(c.id, "active", "ok", "human")
    c = s.record_adjustment(adjust_confidence(c, False), "miss", "score")
    assert c.confidence == pytest.approx(0.45)
    assert [h.reason for h in s.history(c.id)] == ["proposed", "ok", "miss"]


def test_retired_claim_never_feeds_prediction():
    s = MemoryStore()
    a = s.propose_claim("a", "x", "prior", [], "t")
    b = s.propose_claim("a", "y", "prior", [], "t")
    s.confirm_or_retire(a.id, "active", "ok", "human")
    s.confirm_or_retire(b.id, "active", "ok", "human")
    s.confirm_or_retire(b.id, "retired", "missed", "human")
    assert [c.id for c in s.query_claims(athlete_id="a", status="active")] == [a.id]
    assert replace(b, status=Status.RETIRED).status == Status.RETIRED
