"""chat-layer 2.4: the loop with a fake model client, no network."""

import asyncio
import json
from types import SimpleNamespace

from domestique.chat.check import MARK
from domestique.chat.loop import (
    AnthropicModel,
    ChatSettings,
    Conversation,
    Loop,
    ToolCall,
    Turn,
    chat_settings,
)
from domestique.chat.tools import ToolOutput, names

LABELLED = "- (your data shows) HRV 71 against a baseline of 82.\n- (you told me) Legs felt heavy."
UNLABELLED = "- (your data shows) HRV 71 against a baseline of 82.\n- Rest today."
RAIL = "Synthetic rail wording: talk to a clinician before riding."


class FakeModel:
    """Returns scripted turns in order and records every request."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests = []

    async def turn(self, *, model, system, messages, tools, on_text):
        self.requests.append(
            {"model": model, "system": system, "messages": list(messages), "tools": tools}
        )
        turn = self.turns.pop(0)
        if on_text is not None and turn.text:
            await on_text(turn.text)
        return turn


def say(text, stop="end_turn"):
    return Turn([{"type": "text", "text": text}], text, (), stop)


def call(name, args, cid="tu-1"):
    block = {"type": "tool_use", "id": cid, "name": name, "input": args}
    return Turn([block], "", (ToolCall(cid, name, args),), "tool_use")


class FakeTools:
    def __init__(self, outputs=None):
        self.outputs = outputs or {}
        self.calls = []

    async def run(self, name, raw_args):
        self.calls.append((name, raw_args))
        return self.outputs.get(name, ToolOutput("{}"))


class Screen:
    def __init__(self):
        self.shown = ""
        self.resets = 0
        self.tools = []

    async def text(self, token):
        self.shown += token

    async def reset(self):
        self.shown = ""
        self.resets += 1

    async def tool(self, name, output):
        self.tools.append(name)


def respond(model, convo, text="How am I today?", tools=None):
    screen = Screen()
    loop = Loop(model, tools or FakeTools(), ChatSettings())
    reply = asyncio.run(loop.respond(convo, text, screen))
    return reply, screen


def test_a_labelled_reply_is_shown_as_is():
    model = FakeModel(say(LABELLED))
    reply, screen = respond(model, Conversation("system prompt"))
    assert reply.text == LABELLED and not reply.retried and reply.unlabelled == ()
    assert screen.shown == LABELLED and screen.resets == 0
    assert len(model.requests) == 1


def test_an_unlabelled_reply_is_retried_once_then_shown_marked():
    model = FakeModel(say(UNLABELLED), say(UNLABELLED))
    convo = Conversation("system prompt")
    reply, screen = respond(model, convo)
    assert len(model.requests) == 2
    note = model.requests[1]["messages"][-1]
    assert note["role"] == "user" and "- Rest today." in note["content"]
    assert reply.retried and reply.unlabelled == ("Rest today.",)
    assert reply.text.endswith(f"- {MARK} Rest today.")
    assert "(your data shows) HRV 71" in reply.text and MARK not in reply.text.splitlines()[0]
    assert screen.resets == 1


def test_a_fixed_retry_is_shown_without_marks():
    model = FakeModel(say(UNLABELLED), say(LABELLED))
    reply, _ = respond(model, Conversation("system prompt"))
    assert reply.retried and reply.text == LABELLED and MARK not in reply.text


def test_tool_results_reach_the_model_and_their_rail_wording_is_exempt():
    day = ToolOutput(json.dumps({"rails": [{"wording": RAIL}]}), exempt=(RAIL,))
    tools = FakeTools({"console_day": day})
    model = FakeModel(call("console_day", {"date": "2026-09-09"}), say(RAIL))
    convo = Conversation("system prompt")
    reply, screen = respond(model, convo, tools=tools)
    assert tools.calls == [("console_day", {"date": "2026-09-09"})]
    assert reply.text == RAIL and not reply.retried
    second = model.requests[1]["messages"]
    assert second[-1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": day.content}],
    }
    assert names(model.requests[0]["tools"]) == {
        "console_claims",
        "console_day",
        "console_questions",
        "query_claims",
        "propose_claim",
        "attach_evidence",
    }
    assert screen.tools == ["console_day"] and convo.exempt == [RAIL]


def test_a_refusal_leaves_the_history_as_it_was():
    convo = Conversation("system prompt")
    respond(FakeModel(say(LABELLED)), convo)
    before = list(convo.messages)
    reply, _ = respond(FakeModel(call("console_claims", {}), say("", "refusal")), convo)
    assert reply.declined and convo.messages == before


def test_weekly_review_final_pass_uses_the_summary_model():
    settings = ChatSettings(model="reasoning-model", summary_model="summary-model")
    model = FakeModel(say("draft without labels."), say(LABELLED))
    loop = Loop(model, FakeTools(), settings)
    screen = Screen()
    convo = Conversation("weekly system", summary_pass=True)
    reply = asyncio.run(loop.respond(convo, "Review my week", screen))
    assert [r["model"] for r in model.requests] == ["reasoning-model", "summary-model"]
    assert model.requests[1]["tools"] == []
    assert "draft without labels." in model.requests[1]["messages"][0]["content"]
    assert reply.text == LABELLED and screen.shown == LABELLED  # the draft never streams


def test_other_modes_never_use_the_summary_model():
    settings = ChatSettings(model="reasoning-model", summary_model="summary-model")
    model = FakeModel(say(UNLABELLED), say(UNLABELLED))
    asyncio.run(Loop(model, FakeTools(), settings).respond(Conversation("s"), "hi", Screen()))
    assert {r["model"] for r in model.requests} == {"reasoning-model"}


def test_settings_default_to_opus_and_the_env_overrides_the_model():
    assert chat_settings({}).model == "claude-opus-5-5"
    assert chat_settings({"DOMESTIQUE_CHAT_MODEL": "other"}).model == "other"
    assert chat_settings({"DOMESTIQUE_CHAT_SUMMARY_MODEL": "cheap"}).summary_model == "cheap"


class FakeStream:
    def __init__(self, message):
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def events():
            yield SimpleNamespace(type="text", text="Hel")
            yield SimpleNamespace(type="text", text="lo.")

        return events()

    async def get_final_message(self):
        return self.message


def test_anthropic_model_streams_and_converts_the_final_message():
    block_text = SimpleNamespace(type="text", text="Hello.")
    block_tool = SimpleNamespace(type="tool_use", id="t1", name="console_questions", input={})
    message = SimpleNamespace(content=[block_text, block_tool], stop_reason="tool_use")
    seen = {}

    def stream(**params):
        seen.update(params)
        return FakeStream(message)

    sdk = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    tokens = []

    async def on_text(t):
        tokens.append(t)

    turn = asyncio.run(
        AnthropicModel(sdk, ChatSettings()).turn(
            model="claude-opus-5-5", system="s", messages=[], tools=[], on_text=on_text
        )
    )
    assert tokens == ["Hel", "lo."]
    assert turn.text == "Hello." and turn.stop_reason == "tool_use"
    assert turn.tool_calls == (ToolCall("t1", "console_questions", {}),)
    assert turn.content == [block_text, block_tool]
    assert seen["thinking"] == {"type": "adaptive"} and "tools" not in seen
    assert seen["fallbacks"] == "default"
