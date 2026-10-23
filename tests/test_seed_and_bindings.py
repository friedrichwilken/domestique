"""Seed loader with bindings, and the claims MCP add_binding tool."""

import importlib.util
from pathlib import Path

import pytest

from domestique.claims.seed import load_seed, parse_seed, read_seed
from domestique.claims.store import MemoryStore
from domestique.loop.model import Metric
from domestique.loop.store import MemoryLoopStore

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "evals/fixtures/claims_seed.yaml"
PRIORS = ROOT / "evals/priors.yaml"


def test_claims_seed_loads_with_its_bindings():
    seed = read_seed(SEED)
    claims, loop = MemoryStore(), MemoryLoopStore()
    loaded = load_seed(seed, claims, loop)
    assert len(loaded) == len(seed.claims)
    assert all(c.status == "candidate" for c, _ in loaded)  # human gate kept by default
    bound = {c.text: tuple(b.metric for b in bs) for c, bs in loaded if bs}
    assert bound == {
        "Next-morning HRV drops 8-12% after sessions with more than 20 min above threshold.": (
            Metric.HRV_NEXT_MORNING,
        ),
        "Sleep duration falls about 40 min on nights after evening intensity.": (
            Metric.SLEEP_HOURS,
        ),
    }
    sleep = next(b for _, bs in loaded for b in bs if b.metric == Metric.SLEEP_HOURS)
    assert (sleep.offset, sleep.when.start_hour_from, sleep.when.min_if) == (-0.67, 17, 0.85)
    assert len(loop.bindings(seed.athlete_id)) == 2


def test_priors_seed_is_prior_only_and_activates_in_a_working_store():
    seed = read_seed(PRIORS)
    assert {c.source_layer for c in seed.claims} == {"prior"}
    claims, loop = MemoryStore(), MemoryLoopStore()
    loaded = load_seed(seed, claims, loop, athlete_id="someone", activate=True)
    assert {c.status for c, _ in loaded} == {"active"}
    assert {c.athlete_id for c, _ in loaded} == {"someone"}
    assert {b.metric for b in loop.bindings("someone")} == set(Metric)


def test_bad_binding_fails_the_whole_file_before_any_write():
    raw = {
        "athlete_id": "a",
        "claims": [
            {
                "text": "x",
                "source_layer": "prior",
                "horizon": "day",
                "evidence": [],
                "bindings": [{"metric": "sleep_hours", "params": {"offset": -1}}],
            }
        ],
    }
    with pytest.raises(ValueError, match="zero-width"):
        parse_seed(raw)
    raw["claims"][0]["bindings"] = [{"metric": "mood", "params": {"range_abs": 1}}]
    with pytest.raises(ValueError, match="mood"):
        parse_seed(raw)


@pytest.fixture
def server():
    spec = importlib.util.spec_from_file_location("claims_server", ROOT / "mcp/claims/server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    loop = MemoryLoopStore()
    mod.set_store(MemoryStore(), loop)
    return mod, loop


def test_add_binding_on_a_candidate_needs_no_token(server):
    mod, loop = server
    c = mod.propose_claim("a", "sleep after evening intensity", "prior", "day", [])
    out = mod.add_binding(
        c["id"],
        "sleep_hours",
        {"offset": -1.0, "range_abs": 0.5},
        {"min_if": 0.85, "start_hour_from": 17, "start_hour_to": 23},
    )
    assert out["metric"] == "sleep_hours" and out["conditions"]["start_hour_from"] == 17
    (b,) = loop.bindings("a")
    assert b.claim_id == c["id"] and b.offset == -1.0


def test_add_binding_on_an_active_claim_is_human_gated(server, monkeypatch):
    mod, loop = server
    monkeypatch.setenv("DOMESTIQUE_HUMAN_TOKEN", "secret")
    c = mod.propose_claim("a", "x", "prior", "day", [])
    mod.confirm_or_retire(c["id"], "active", "r", "secret")
    with pytest.raises(mod.HumanTokenError):
        mod.add_binding(c["id"], "peak_hr", {"offset": 5, "range_abs": 4})
    assert loop.bindings("a") == []
    mod.add_binding(c["id"], "peak_hr", {"offset": 5, "range_abs": 4}, human_token="secret")
    assert len(loop.bindings("a")) == 1


def test_add_binding_validates_before_writing(server):
    mod, loop = server
    c = mod.propose_claim("a", "x", "prior", "day", [])
    with pytest.raises(ValueError, match="unknown binding params"):
        mod.add_binding(c["id"], "peak_hr", {"range_abs": 4, "fudge": 1})
    with pytest.raises(ValueError, match="zero-width"):
        mod.add_binding(c["id"], "peak_hr", {"offset": 4})
    with pytest.raises(mod.ClaimNotFoundError):
        mod.add_binding("nope", "peak_hr", {"range_abs": 4})
    assert loop.bindings("a") == []
