"""Claims MCP server (stdio).

Tools: query_claims, propose_claim, attach_evidence, confirm_or_retire.
confirm_or_retire is human-gated: it refuses unless ``human_token`` equals the
DOMESTIQUE_HUMAN_TOKEN environment variable. Storage: Postgres via
DOMESTIQUE_DATABASE_URL. See README.md.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import asdict
from typing import Any

import psycopg
from mcp.server.fastmcp import FastMCP

from domestique.claims.store import Claim, ClaimsStore, Evidence, EvidenceInput, PgStore

mcp = FastMCP("domestique-claims")
AGENT = "agent:claims-mcp"


class HumanTokenError(PermissionError):
    pass


class _StoreHolder:
    """The process-wide store: created lazily from the environment, replaceable for tests."""

    store: ClaimsStore | None = None


_holder = _StoreHolder()


def require_human(token: str | None) -> None:
    expected = os.environ.get("DOMESTIQUE_HUMAN_TOKEN", "")
    if not expected:
        raise HumanTokenError("DOMESTIQUE_HUMAN_TOKEN is not set; confirm_or_retire is disabled")
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HumanTokenError("a valid human token is required for confirm_or_retire")


def get_store() -> ClaimsStore:
    if _holder.store is None:
        _holder.store = PgStore(
            psycopg.connect(os.environ["DOMESTIQUE_DATABASE_URL"], autocommit=True)
        )
    return _holder.store


def set_store(store: ClaimsStore) -> None:
    """Inject a store (tests)."""
    _holder.store = store


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


@mcp.tool()
def confirm_or_retire(claim_id: str, status: str, reason: str, human_token: str) -> dict[str, Any]:
    """Set a claim to 'active' or 'retired'. Human-gated: needs the human token."""
    require_human(human_token)
    return _plain(get_store().confirm_or_retire(claim_id, status, reason, "human"))


if __name__ == "__main__":
    mcp.run(transport="stdio")
