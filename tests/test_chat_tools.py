"""chat-layer 2.2: the six tools the model receives, and how each one runs."""

import asyncio
import importlib.util
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from domestique.chat import tools
from domestique.chat.tools import GATED, McpClaims, ToolBox, ToolCallError, api_tools
from domestique.claims.store import MemoryStore
from domestique.ingest.plan_store import MemoryPlanStore
from domestique.rails import DayData, joint_pain
from domestique.web.app import WebSettings, create_app
from domestique.web.day import DaySettings, OpenQuestion, build_day
from domestique.web.queries import ReportData

ROOT = Path(__file__).resolve().parents[1]
ATHLETE = "athlete-synth-1"
DAY = date(2026, 9, 9)
SIX = {
    "console_claims",
    "console_day",
    "console_questions",
    "query_claims",
    "propose_claim",
    "attach_evidence",
}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def server():
    spec = importlib.util.spec_from_file_location("claims_server", ROOT / "mcp/claims/server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.set_store(MemoryStore())
    return mod


def claims_over_mcp(server):
    return McpClaims(lambda: create_connected_server_and_client_session(server.mcp))


def test_the_model_receives_exactly_the_six_tools():
    received = api_tools()
    assert tools.names(received) == SIX
    assert len(received) == len(SIX)
    assert all(t["input_schema"]["type"] == "object" for t in received)


def test_gated_tool_names_are_absent_everywhere_in_the_list():
    assert {"confirm_or_retire", "add_binding", "clear_flags"} == GATED
    dumped = json.dumps(api_tools())
    for name in GATED:
        assert name not in dumped
    assert not GATED & {t.name for t in tools.TOOLS}


def test_claims_tool_schemas_match_the_server(server):
    async def listed():
        async with create_connected_server_and_client_session(server.mcp) as session:
            return {t.name: t.inputSchema for t in (await session.list_tools()).tools}

    on_server = run(listed())
    for tool in tools.CLAIMS_TOOLS:
        schema = on_server[tool.name]
        assert set(tool.properties) == set(schema["properties"])
        assert set(tool.required) == set(schema.get("required", []))


def test_propose_and_query_through_the_mcp_session(server):
    box = ToolBox(httpx.AsyncClient(), claims_over_mcp(server))
    args = {
        "athlete_id": ATHLETE,
        "text": "synthetic pattern",
        "source_layer": "observed",
        "horizon": "day",
        "evidence": [{"kind": "activity", "ref": "a-1"}],
    }
    proposed = run(box.run("propose_claim", args))
    assert not proposed.is_error, proposed.content
    claim = json.loads(proposed.content)
    assert claim["status"] == "candidate"
    queried = json.loads(run(box.run("query_claims", {"status": "candidate"})).content)
    assert [c["id"] for c in queried] == [claim["id"]]
    attached = run(box.run("attach_evidence", {"claim_id": claim["id"], "kind": "x", "ref": "r"}))
    assert attached.is_error  # unknown kind: the server's error goes back to the model


def test_gated_names_are_refused_even_if_asked_for(server):
    box = ToolBox(httpx.AsyncClient(), claims_over_mcp(server))
    out = run(box.run("confirm_or_retire", {"claim_id": "x", "status": "active"}))
    assert out.is_error and "not an available tool" in out.content
    with pytest.raises(ToolCallError):
        run(claims_over_mcp(server).call("clear_flags", {"claim_id": "x", "reason": "r"}))


def test_bad_arguments_are_returned_as_errors_without_running(server):
    box = ToolBox(httpx.AsyncClient(), claims_over_mcp(server))
    assert run(box.run("propose_claim", {"text": "no layer"})).is_error
    assert run(box.run("console_day", {"date": "yesterday"})).is_error
    assert run(box.run("query_claims", {"status": 3})).is_error
    assert server.query_claims() == []


def test_console_tools_read_the_console_json_and_collect_the_exempt_text():
    rail_day = DayData(DAY, subjective_tags=("joint-pain",))
    wording = joint_pain(rail_day, {}).wording
    asked = OpenQuestion(
        "q-1", "athlete", "Was the last climb planned?", datetime(2026, 9, 9, 20, tzinfo=UTC)
    )
    view = build_day(ATHLETE, rail_day, DaySettings(), MemoryPlanStore(), [asked])
    app = create_app(
        WebSettings(ATHLETE, None),
        report=lambda: ReportData(ATHLETE, ()),
        day=lambda d: view,
        store=lambda: pytest.fail("not used"),
        questions=lambda: [asked],
    )
    console = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app")
    box = ToolBox(console, claims=None)

    day = run(box.run("console_day", {"date": "2026-09-09"}))
    assert json.loads(day.content)["rails"][0]["wording"] == wording
    assert set(day.exempt) == {wording, asked.text}
    questions = run(box.run("console_questions", {}))
    assert questions.exempt == (asked.text,)
    claims = run(box.run("console_claims", {}))
    assert json.loads(claims.content) == {"athlete_id": ATHLETE, "claims": []}


def test_settings_from_the_environment():
    s = tools.tool_settings({})
    assert s.console_url == "http://app:8000" and s.claims_url is None
    assert s.claims_server == ROOT / "mcp/claims/server.py"
    s = tools.tool_settings(
        {
            "DOMESTIQUE_CONSOLE_URL": "http://127.0.0.1:8000",
            "DOMESTIQUE_CLAIMS_MCP_URL": "http://x/mcp",
        }
    )
    assert s.console_url == "http://127.0.0.1:8000" and s.claims_url == "http://x/mcp"
