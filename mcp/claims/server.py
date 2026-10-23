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

from mcp.server.fastmcp import FastMCP

from domestique.claims.store import ClaimsStore, PgStore

mcp = FastMCP("domestique-claims")
_store: ClaimsStore | None = None
AGENT = "agent:claims-mcp"


class HumanTokenError(PermissionError):
    pass


def require_human(token: str | None) -> None:
    expected = os.environ.get("DOMESTIQUE_HUMAN_TOKEN", "")
    if not expected:
        raise HumanTokenError("DOMESTIQUE_HUMAN_TOKEN is not set; confirm_or_retire is disabled")
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HumanTokenError("a valid human token is required for confirm_or_retire")


def get_store() -> ClaimsStore:
    global _store
    if _store is None:
        import psycopg

        _store = PgStore(psycopg.connect(os.environ["DOMESTIQUE_DATABASE_URL"], autocommit=True))
    return _store


def set_store(store: ClaimsStore) -> None:
    """Inject a store (tests)."""
    global _store
    _store = store


def _plain(obj: Any) -> Any:
    d = asdict(obj)
    return {k: (v.isoformat() if hasattr(v, "isoformat") else getattr(v, "value", v))
            for k, v in d.items()}


@mcp.tool()
def query_claims(
    athlete_id: str | None = None,
    source_layer: str | None = None,
    status: str | None = None,
    text_contains: str | None = None,
) -> list[dict]:
    """List claims, optionally filtered by athlete, source layer, status or text."""
    return [_plain(c) for c in get_store().query_claims(
        athlete_id, source_layer, status, text_contains)]


@mcp.tool()
def propose_claim(
    athlete_id: str, text: str, source_layer: str, evidence: list[dict]
) -> dict:
    """Propose a claim. Always created with status 'candidate'.

    source_layer is observed, stated or prior; evidence is a list of
    {kind, ref, note?} with kind in activity, interval, wellness, statement,
    reference, query.
    """
    return _plain(get_store().propose_claim(athlete_id, text, source_layer, evidence, AGENT))


@mcp.tool()
def attach_evidence(claim_id: str, kind: str, ref: str, note: str | None = None) -> dict:
    """Attach one evidence entry to an existing claim."""
    return _plain(get_store().attach_evidence(claim_id, kind, ref, note))


@mcp.tool()
def confirm_or_retire(claim_id: str, status: str, reason: str, human_token: str) -> dict:
    """Set a claim to 'active' or 'retired'. Human-gated: needs the human token."""
    require_human(human_token)
    return _plain(get_store().confirm_or_retire(claim_id, status, reason, "human"))


if __name__ == "__main__":
    mcp.run(transport="stdio")
