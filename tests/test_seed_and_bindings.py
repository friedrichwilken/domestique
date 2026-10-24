"""Seed loader with bindings, and the claims MCP add_binding tool."""

import importlib.util
import os
import uuid
from pathlib import Path

import pytest

from domestique import db
from domestique.claims import seed as seed_cli
from domestique.claims.gate import HumanTokenError
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
    with pytest.raises(HumanTokenError):
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


# --- seed command line -------------------------------------------------------

TWO_CLAIMS = """\
athlete_id: athlete-synth-2
claims:
  - text: "Peak heart rate runs a few beats above the prescribed band."
    source_layer: prior
    horizon: day
    confidence: 0.5
    evidence:
      - {kind: reference, ref: textbook-hr-peaks}
    bindings:
      - metric: peak_hr
        params: {offset: 5, range_abs: 4}
  - text: "Sleep after an easy session stays at the recent median."
    source_layer: prior
    horizon: day
    confidence: 0.5
    evidence:
      - {kind: reference, ref: textbook-exercise-sleep-null}
    bindings:
      - metric: sleep_hours
        params: {range_abs: 0.3}
        conditions: {max_if: 0.84}
"""


def test_seed_args_default_to_not_activated():
    args = seed_cli.parse_args(["--file", "evals/priors.yaml"])
    assert (args.file, args.activate, args.athlete_id) == (Path("evals/priors.yaml"), False, None)
    args = seed_cli.parse_args(["--file", "x.yaml", "--activate", "--athlete-id", "iZ"])
    assert (args.activate, args.athlete_id) == (True, "iZ")
    with pytest.raises(SystemExit):
        seed_cli.parse_args([])


def test_seed_athlete_id_flag_wins_over_environment():
    env = {"ICU_ATHLETE_ID": "iEnv", "DOMESTIQUE_DSN": "postgresql://env/db"}
    args = seed_cli.parse_args(["--file", "x.yaml"])
    assert seed_cli.settings(args, env) == ("iEnv", "postgresql://env/db")
    args = seed_cli.parse_args(["--file", "x.yaml", "--athlete-id", "iFlag"])
    assert seed_cli.settings(args, env) == ("iFlag", "postgresql://env/db")


@pytest.mark.skipif(not os.environ.get("DOMESTIQUE_TEST_DSN"), reason="needs a Postgres DSN")
def test_seed_command_writes_candidates_and_bindings(tmp_path, capsys):
    path = tmp_path / "seed.yaml"
    path.write_text(TWO_CLAIMS)
    athlete = f"iT{uuid.uuid4().hex[:8]}"
    dsn = os.environ["DOMESTIQUE_TEST_DSN"]
    seed_cli.main(["--file", str(path), "--athlete-id", athlete], {"DOMESTIQUE_DSN": dsn})
    assert capsys.readouterr().out == "seeded 2 claims (candidate), 2 bindings\n"
    with db.connect(dsn) as conn:
        statuses = conn.execute(
            "SELECT status FROM claims WHERE athlete_id = %s", (athlete,)
        ).fetchall()
        (n_bindings,) = conn.execute(
            "SELECT count(*) FROM claim_bindings b JOIN claims c ON c.id = b.claim_id "
            "WHERE c.athlete_id = %s",
            (athlete,),
        ).fetchone()
    assert statuses == [("candidate",), ("candidate",)]
    assert n_bindings == 2
