"""Claims MCP server (stdio).

Tools: query_claims, propose_claim, attach_evidence, add_binding, confirm_or_retire,
clear_flags. confirm_or_retire and clear_flags are human-gated: they refuse unless
``human_token`` equals the DOMESTIQUE_HUMAN_TOKEN environment variable. add_binding
is gated the same way unless the claim is still a candidate. Storage: Postgres via
DOMESTIQUE_DATABASE_URL. See README.md.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

import psycopg
from mcp.server.fastmcp import FastMCP

from domestique.claims.gate import require_human
from domestique.claims.rules import Status
from domestique.claims.store import (
    Claim,
    ClaimNotFoundError,
    ClaimsStore,
    Evidence,
    EvidenceInput,
    PgStore,
)
from domestique.loop.model import binding_params, conditions_json, parse_binding
from domestique.loop.store import LoopStore, PgLoopStore

mcp = FastMCP("domestique-claims")
AGENT = "agent:claims-mcp"


class _StoreHolder:
    """The process-wide stores: created lazily from the environment, replaceable for tests."""

    store: ClaimsStore | None = None
    loop: LoopStore | None = None
    conn: psycopg.Connection[tuple[Any, ...]] | None = None


_holder = _StoreHolder()


def _conn() -> psycopg.Connection[tuple[Any, ...]]:
    if _holder.conn is None:
        _holder.conn = psycopg.connect(os.environ["DOMESTIQUE_DATABASE_URL"], autocommit=True)
    return _holder.conn


def get_store() -> ClaimsStore:
    if _holder.store is None:
        _holder.store = PgStore(_conn())
    return _holder.store


def get_loop_store() -> LoopStore:
    if _holder.loop is None:
        _holder.loop = PgLoopStore(_conn())
    return _holder.loop


def set_store(store: ClaimsStore, loop: LoopStore | None = None) -> None:
    """Inject stores (tests)."""
    _holder.store = store
    _holder.loop = loop


def _plain(obj: Claim | Evidence) -> dict[str, Any]:
    """Dataclass to a JSON-friendly dict. ``Any``: this is the MCP output boundary."""
    d = asdict(obj)
    return {
        k: (v.isoformat() if hasattr(v, "isoformat") else getattr(v, "value", v))
        for k, v in d.items()
    }


@mcp.tool()
def query_claims(
    athlete_id: str | None = None,
    source_layer: str | None = None,
    status: str | None = None,
    text_contains: str | None = None,
) -> list[dict[str, Any]]:
    """List claims, optionally filtered by athlete, source layer, status or text."""
    return [
        _plain(c) for c in get_store().query_claims(athlete_id, source_layer, status, text_contains)
    ]


@mcp.tool()
def propose_claim(
    athlete_id: str,
    text: str,
    source_layer: str,
    horizon: str,
    evidence: list[EvidenceInput],
) -> dict[str, Any]:
    """Propose a claim. Always created with status 'candidate'.

    source_layer is observed, stated or prior. horizon is day, week or season
    (how long until its predictions can be scored); a claim without one is
    rejected. Season claims stay prior and are capped at 0.5. evidence is a list of
    {kind, ref, note?} with kind in activity, interval, wellness, statement,
    reference, query.
    """
    return _plain(
        get_store().propose_claim(athlete_id, text, source_layer, horizon, evidence, AGENT)
    )


@mcp.tool()
def attach_evidence(claim_id: str, kind: str, ref: str, note: str | None = None) -> dict[str, Any]:
    """Attach one evidence entry to an existing claim."""
    return _plain(get_store().attach_evidence(claim_id, kind, ref, note))


def _claim(claim_id: str) -> Claim:
    for c in get_store().query_claims():
        if c.id == claim_id:
            return c
    raise ClaimNotFoundError(claim_id)


@mcp.tool()
def add_binding(
    claim_id: str,
    metric: str,
    params: dict[str, Any],
    conditions: dict[str, Any] | None = None,
    human_token: str | None = None,
) -> dict[str, Any]:
    """Bind a claim to one predicted metric, so the claim can feed predictions.

    metric is watts_at_hr, peak_hr, hrv_next_morning or sleep_hours. params:
    change_pct, offset, range_pct, range_abs (a range is required), rides
    (watts_at_hr only). expected = base * (1 + change_pct/100) + offset, range
    expected -/+ (expected * range_pct/100 + range_abs). conditions (all
    optional): min_if, max_if, sports, start_hour_from, start_hour_to.
    Replaces an existing binding for the same claim and metric. Free for a
    candidate claim; on an active or retired claim it changes what the athlete
    model predicts, so it needs the human token.
    """
    binding = parse_binding(claim_id, metric, params, conditions or {})
    if _claim(claim_id).status != Status.CANDIDATE:
        require_human(human_token, "add_binding on a claim that is not a candidate")
    get_loop_store().add_binding(binding)
    return {
        "claim_id": binding.claim_id,
        "metric": binding.metric.value,
        "params": binding_params(binding),
        "conditions": conditions_json(binding.when),
    }


@mcp.tool()
def confirm_or_retire(claim_id: str, status: str, reason: str, human_token: str) -> dict[str, Any]:
    """Set a claim to 'active' or 'retired'. Human-gated: needs the human token."""
    require_human(human_token)
    return _plain(get_store().confirm_or_retire(claim_id, status, reason, "human"))


@mcp.tool()
def clear_flags(claim_id: str, reason: str, human_token: str) -> dict[str, Any]:
    """Clear a claim's uninformative and overconfident flags. Human-gated.

    Use after the claim's range was changed (add_binding) at review. Clearing starts
    a new calibration window: the flags are judged again after ten more outcomes.
    """
    require_human(human_token, "clear_flags")
    return _plain(get_store().clear_flags(claim_id, reason, "human"))


if __name__ == "__main__":
    mcp.run(transport="stdio")
