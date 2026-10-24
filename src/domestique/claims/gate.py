"""The human gate: one token check shared by every door to a human-only decision.

The claims MCP server and the web console both call ``require_human``; there is
no second implementation. The token is ``DOMESTIQUE_HUMAN_TOKEN`` from the
environment, compared in constant time. Unset means the gate is closed.
"""

from __future__ import annotations

import hmac
import os


class HumanTokenError(PermissionError):
    pass


def require_human(token: str | None, tool: str = "confirm_or_retire") -> None:
    expected = os.environ.get("DOMESTIQUE_HUMAN_TOKEN", "")
    if not expected:
        raise HumanTokenError(f"DOMESTIQUE_HUMAN_TOKEN is not set; {tool} is disabled")
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HumanTokenError(f"a valid human token is required for {tool}")
