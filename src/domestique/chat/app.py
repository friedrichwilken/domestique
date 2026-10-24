"""The Chainlit app: pick a mode, talk to it, every reply checked for source layers.

Run with ``chainlit run src/domestique/chat/app.py``. The mode is chosen as a
chat profile, one per skill file. Each conversation keeps its own message
history in the Chainlit session; athlete state stays behind the console and
the claims server. The agent loop lives in ``domestique.chat.loop``; this file
only wires it to the UI.
"""

from __future__ import annotations

import chainlit as cl
from anthropic import AsyncAnthropic

from domestique import config
from domestique.chat.loop import AnthropicModel, Conversation, Loop, chat_settings
from domestique.chat.modes import MODES, context_for, describe, load_mode
from domestique.chat.tools import ToolOutput, tool_settings, toolbox

SUMMARY_MODES = frozenset({"weekly-review"})
TOOL_OUTPUT_SHOWN = 4000  # characters of a tool result shown in its step


class ChainlitSink:
    """Streams the reply into one Chainlit message and shows each tool call as a step."""

    def __init__(self, message: cl.Message) -> None:
        self.message = message

    async def text(self, token: str) -> None:
        await self.message.stream_token(token)

    async def reset(self) -> None:
        self.message.content = ""
        await self.message.update()

    async def tool(self, name: str, output: ToolOutput) -> None:
        async with cl.Step(name=name, type="tool") as step:
            step.output = output.content[:TOOL_OUTPUT_SHOWN]
            step.is_error = output.is_error


@cl.set_chat_profiles
async def chat_profiles(
    _user: cl.User | None = None, _language: str | None = None
) -> list[cl.ChatProfile]:
    return [
        cl.ChatProfile(name=name, markdown_description=describe(name), default=i == 0)
        for i, name in enumerate(MODES)
    ]


@cl.on_chat_start
async def start() -> None:
    name = cl.user_session.get("chat_profile") or MODES[0]
    cfg = config.load()  # athlete id and timezone for the prompt prefix
    mode = load_mode(name, context_for(cfg.athlete_id, cfg.timezone))
    settings = chat_settings()
    loop = Loop(AnthropicModel(AsyncAnthropic(), settings), toolbox(tool_settings()), settings)
    cl.user_session.set("conversation", Conversation(mode.system, name in SUMMARY_MODES))
    cl.user_session.set("loop", loop)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    convo: Conversation = cl.user_session.get("conversation")
    loop: Loop = cl.user_session.get("loop")
    out = cl.Message(content="")
    reply = await loop.respond(convo, message.content, ChainlitSink(out))
    out.content = reply.text
    await out.send()
