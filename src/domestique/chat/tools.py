"""The model's tools: a static allow-list of six, three console reads and three claims tools.

``TOOLS`` is the whole list the model receives. The console tools are HTTP GETs
against the console's JSON routes (``DOMESTIQUE_CONSOLE_URL``, default
``http://app:8000``). The claims tools are calls into the claims MCP server
through an MCP client session, over streamable HTTP when
``DOMESTIQUE_CLAIMS_MCP_URL`` is set, otherwise over stdio by starting
``mcp/claims/server.py`` without the human token in its environment. The gated
tools (``confirm_or_retire``, ``add_binding``, ``clear_flags``) are not in the
list and ``McpClaims`` refuses any name outside it: the model proposes, a human
decides through the console's form.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

GATED: frozenset[str] = frozenset({"confirm_or_retire", "add_binding", "clear_flags"})
DEFAULT_CONSOLE_URL = "http://app:8000"
DEFAULT_CLAIMS_SERVER = Path(__file__).resolve().parents[3] / "mcp" / "claims" / "server.py"

_STR: dict[str, Any] = {"type": "string"}
_EVIDENCE: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"kind": _STR, "ref": _STR, "note": _STR},
        "required": ["kind", "ref"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {k: dict(v) for k, v in self.properties.items()},
            "required": list(self.required),
            "additionalProperties": False,
        }


CONSOLE_TOOLS: tuple[Tool, ...] = (
    Tool(
        "console_claims",
        "The claims report from the console: every claim with status, source layer, "
        "horizon, confidence, scored predictions, hit rate, calibration flags and history.",
    ),
    Tool(
        "console_day",
        "One day from the console: rails results (withholding rails first, wording verbatim), "
        "plan versus execution unless a rail withholds it, and the day's open questions.",
        {"date": {"type": "string", "description": "YYYY-MM-DD"}},
        ("date",),
    ),
    Tool(
        "console_questions",
        "Every open question for the athlete or the reviewer, text verbatim.",
    ),
)
CLAIMS_TOOLS: tuple[Tool, ...] = (
    Tool(
        "query_claims",
        "List claims, optionally filtered by athlete, source layer, status or text.",
        {"athlete_id": _STR, "source_layer": _STR, "status": _STR, "text_contains": _STR},
    ),
    Tool(
        "propose_claim",
        "Propose a claim; it is always created as a candidate that a human reviews. "
        "source_layer is observed, stated or prior; horizon is day, week or season. "
        "evidence is a list of {kind, ref, note?} with kind in activity, interval, wellness, "
        "statement, reference, query.",
        {
            "athlete_id": _STR,
            "text": _STR,
            "source_layer": _STR,
            "horizon": _STR,
            "evidence": _EVIDENCE,
        },
        ("athlete_id", "text", "source_layer", "horizon", "evidence"),
    ),
    Tool(
        "attach_evidence",
        "Attach one evidence entry to an existing claim.",
        {"claim_id": _STR, "kind": _STR, "ref": _STR, "note": _STR},
        ("claim_id", "kind", "ref"),
    ),
)
TOOLS: tuple[Tool, ...] = CONSOLE_TOOLS + CLAIMS_TOOLS
_BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


def api_tools() -> list[dict[str, Any]]:
    """The tool definitions the model receives, in the Messages API shape."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.schema(),
            "eager_input_streaming": True,
        }
        for t in TOOLS
    ]


class ToolInputError(ValueError):
    """Arguments that do not match the tool's schema; returned to the model as an error."""


_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "array": list,
    "object": dict,
}


def validate(tool: Tool, args: object) -> dict[str, Any]:
    """Check the model's arguments against the schema before anything runs."""
    if not isinstance(args, dict):
        raise ToolInputError(f"{tool.name}: arguments must be an object")
    unknown = sorted(set(args) - set(tool.properties))
    missing = [k for k in tool.required if k not in args]
    if unknown or missing:
        raise ToolInputError(f"{tool.name}: unknown {unknown}, missing {missing}")
    for key, value in args.items():
        expected = _JSON_TYPES[str(tool.properties[key]["type"])]
        if value is not None and not isinstance(value, expected):
            raise ToolInputError(f"{tool.name}: {key} has the wrong type")
    return dict(args)


# --- what the model must quote unchanged ------------------------------------------


def _texts(items: object, key: str) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(i[key]) for i in items if isinstance(i, dict) and i.get(key)]


def exempt_texts(name: str, payload: object) -> tuple[str, ...]:
    """Rail wording and question text in a console result: shown as they came, unlabelled."""
    if not isinstance(payload, dict):
        return ()
    found = _texts(payload.get("questions"), "text")
    if name == "console_day":
        found += _texts(payload.get("rails"), "wording")
        for row in payload.get("plan_vs_execution") or []:
            if isinstance(row, dict):
                found += [str(q) for q in row.get("questions") or []]
    return tuple(found)


# --- running a call -----------------------------------------------------------------


@dataclass(frozen=True)
class ToolOutput:
    content: str  # what goes back to the model
    is_error: bool = False
    exempt: tuple[str, ...] = ()


class ClaimsClient(Protocol):
    async def call(self, name: str, arguments: dict[str, Any]) -> object: ...


class ToolBox:
    """Runs one of the six tools; anything else is refused."""

    def __init__(self, console: httpx.AsyncClient, claims: ClaimsClient) -> None:
        self.console = console
        self.claims = claims

    async def run(self, name: str, raw_args: object) -> ToolOutput:
        tool = _BY_NAME.get(name)
        if tool is None:
            return ToolOutput(f"{name} is not an available tool", is_error=True)
        try:
            args = validate(tool, raw_args)
            payload = await self._dispatch(name, args)
        except (ToolInputError, ToolCallError, httpx.HTTPError) as exc:
            return ToolOutput(f"{type(exc).__name__}: {exc}", is_error=True)
        return ToolOutput(
            json.dumps(payload, ensure_ascii=False), exempt=exempt_texts(name, payload)
        )

    async def _dispatch(self, name: str, args: dict[str, Any]) -> object:
        if name in {t.name for t in CLAIMS_TOOLS}:
            return await self.claims.call(name, args)
        return await self._get(_console_path(name, args))

    async def _get(self, path: str) -> object:
        response = await self.console.get(path)
        response.raise_for_status()
        return response.json()


def _console_path(name: str, args: Mapping[str, Any]) -> str:
    if name == "console_day":
        try:
            day = date.fromisoformat(str(args["date"]))
        except ValueError:
            raise ToolInputError("console_day: date must be YYYY-MM-DD") from None
        return f"/day/{day.isoformat()}.json"
    return {"console_claims": "/claims.json", "console_questions": "/questions.json"}[name]


# --- the claims MCP server as a client ------------------------------------------------


class ToolCallError(RuntimeError):
    """The claims server refused or failed the call."""


type Connect = Callable[[], AbstractAsyncContextManager[ClientSession]]


class McpClaims:
    """The ungated claims tools through an MCP client session, one session per call."""

    allowed: frozenset[str] = frozenset(t.name for t in CLAIMS_TOOLS)

    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    async def call(self, name: str, arguments: dict[str, Any]) -> object:
        if name not in self.allowed:
            raise ToolCallError(f"{name} is not exposed to the model")
        async with self._connect() as session:
            result = await session.call_tool(name, arguments)
        text = "\n".join(getattr(block, "text", "") for block in result.content)
        if result.isError:
            raise ToolCallError(text or f"{name} failed")
        if result.structuredContent is not None:
            # FastMCP wraps a non-object return value as {"result": ...}
            structured: dict[str, Any] = result.structuredContent
            return structured.get("result", structured)
        return json.loads(text) if text else None


def stdio_connect(server: Path, env: Mapping[str, str]) -> Connect:
    """Start the claims server as a child process, without the human token in its env."""
    child_env = {k: v for k, v in env.items() if k != "DOMESTIQUE_HUMAN_TOKEN"}
    params = StdioServerParameters(command=sys.executable, args=[str(server)], env=child_env)

    @asynccontextmanager
    async def connect() -> AsyncIterator[ClientSession]:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            yield session

    return connect


def http_connect(url: str) -> Connect:
    """Connect to a claims server that runs elsewhere, over streamable HTTP."""

    @asynccontextmanager
    async def connect() -> AsyncIterator[ClientSession]:
        async with (
            streamable_http_client(url) as (read, write, _session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    return connect


@dataclass(frozen=True)
class ToolSettings:
    console_url: str
    claims_url: str | None
    claims_server: Path


def tool_settings(env: Mapping[str, str] | None = None) -> ToolSettings:
    source = os.environ if env is None else env
    server = source.get("DOMESTIQUE_CLAIMS_MCP_SERVER")
    return ToolSettings(
        console_url=source.get("DOMESTIQUE_CONSOLE_URL", DEFAULT_CONSOLE_URL),
        claims_url=source.get("DOMESTIQUE_CLAIMS_MCP_URL") or None,
        claims_server=Path(server) if server else DEFAULT_CLAIMS_SERVER,
    )


def toolbox(settings: ToolSettings, env: Mapping[str, str] | None = None) -> ToolBox:
    """The production tool box: console over HTTP, claims over MCP."""
    connect = (
        http_connect(settings.claims_url)
        if settings.claims_url
        else stdio_connect(settings.claims_server, dict(os.environ if env is None else env))
    )
    console = httpx.AsyncClient(base_url=settings.console_url, timeout=30.0)
    return ToolBox(console, McpClaims(connect))


def names(tools: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(t["name"]) for t in tools}
