import importlib.util
from pathlib import Path

import pytest
import yaml

from domestique.claims.store import ClaimNotFound, MemoryStore

ROOT = Path(__file__).resolve().parents[1]


def test_propose_creates_candidate_with_evidence():
    s = MemoryStore()
    c = s.propose_claim("a", "x", "observed", [{"kind": "activity", "ref": "r"}], "agent")
    assert c.status == "candidate" and len(c.evidence) == 1


def test_no_source_layer_no_claim():
    with pytest.raises(ValueError):
        MemoryStore().propose_claim("a", "x", "vibes", [], "agent")


def test_attach_evidence_and_unknown_claim():
    s = MemoryStore()
    c = s.propose_claim("a", "x", "prior", [], "agent")
    s.attach_evidence(c.id, "reference", "ref")
    assert len(s.query_claims()[0].evidence) == 1
    with pytest.raises(ClaimNotFound):
        s.attach_evidence("nope", "reference", "r")
    with pytest.raises(ValueError):
        s.attach_evidence(c.id, "bogus", "r")


def test_query_filters():
    s = MemoryStore()
    s.propose_claim("a", "alpha", "prior", [], "t")
    s.propose_claim("b", "beta", "observed", [], "t")
    assert len(s.query_claims(athlete_id="a")) == 1
    assert len(s.query_claims(source_layer="observed")) == 1
    assert len(s.query_claims(text_contains="BET")) == 1


def test_seed_file_valid():
    d = yaml.safe_load((ROOT / "evals/fixtures/claims_seed.yaml").read_text())
    assert 18 <= len(d["claims"]) <= 22
    assert {c["source_layer"] for c in d["claims"]} == {"observed", "stated", "prior"}
    s = MemoryStore()
    for c in d["claims"]:
        assert c["evidence"]
        s.propose_claim(d["athlete_id"], c["text"], c["source_layer"], c["evidence"], "seed",
                        c["confidence"])


@pytest.fixture
def server():
    spec = importlib.util.spec_from_file_location("claims_server", ROOT / "mcp/claims/server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.set_store(MemoryStore())
    return mod


def test_confirm_refuses_without_token(server, monkeypatch):
    monkeypatch.setenv("DOMESTIQUE_HUMAN_TOKEN", "secret")
    c = server.propose_claim("a", "x", "prior", [])
    assert c["status"] == "candidate"
    with pytest.raises(server.HumanTokenError):
        server.confirm_or_retire(c["id"], "active", "r", "wrong")
    with pytest.raises(server.HumanTokenError):
        server.confirm_or_retire(c["id"], "active", "r", "")
    assert server.query_claims(status="active") == []
    out = server.confirm_or_retire(c["id"], "active", "r", "secret")
    assert out["status"] == "active"


def test_confirm_disabled_when_env_unset(server, monkeypatch):
    monkeypatch.delenv("DOMESTIQUE_HUMAN_TOKEN", raising=False)
    c = server.propose_claim("a", "x", "prior", [])
    with pytest.raises(server.HumanTokenError):
        server.confirm_or_retire(c["id"], "active", "r", "")
