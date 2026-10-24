"""The agent loop: model turns, tool calls, the layer check, retry once, then mark.

Plain module, no UI and no SDK import at module level: the model client is
injected (``ModelClient``), so tests drive the loop with a scripted fake and no
network. ``AnthropicModel`` is the production client over the Anthropic SDK.

One user message produces one ``Reply``:

1. The model answers, calling tools from the allow-list as it likes. Tool
   results that carry rail wording or question text add that text to the
   conversation's ``exempt`` list.
2. In the weekly review, a cheaper model writes the final text from that
   draft (the summary pass); in every other mode the draft is the answer.
3. ``check_layers`` runs over the answer. Unlabelled statements are sent back
   once with the request to label them; whatever is still unlabelled after
   that is shown marked ``**[unlabelled]**``, never dropped.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from domestique.chat.check import check_layers, mark_unlabelled
from domestique.chat.tools import ToolOutput, api_tools

type Message = dict[str, Any]  # Messages API shape: the external-API boundary
type TextSink = Callable[[str], Awaitable[None]]

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_SUMMARY_MODEL = "claude-sonnet-5-5"
MAX_TOOL_ROUNDS = 25
JSON_RETRIES = 2
RETRY_NOTE = (
    "[response check] These statements carry no source layer. Give your reply again "
    "with every statement labelled (your data shows), (you told me) or "
    "(the literature says). Quote rail wording and question text exactly as the "
    "tools returned them.\n"
)
SUMMARY_NOTE = (
    "[summary pass] Write the final weekly review from the draft below, in the output "
    "shape of this mode. Keep every source-layer label, and quote rail wording and "
    "question text exactly as they appear. Add nothing that is not in the draft.\n\n"
)


@dataclass(frozen=True)
class ChatSettings:
    """Model ids in one place; ``DOMESTIQUE_CHAT_MODEL`` overrides the reasoning model."""

    model: str = DEFAULT_MODEL
    summary_model: str = DEFAULT_SUMMARY_MODEL  # weekly review's final pass only
    max_tokens: int = 64000
    effort: str = "high"


def chat_settings(env: Mapping[str, str] | None = None) -> ChatSettings:
    source = os.environ if env is None else env
    return ChatSettings(
        model=source.get("DOMESTIQUE_CHAT_MODEL") or DEFAULT_MODEL,
        summary_model=source.get("DOMESTIQUE_CHAT_SUMMARY_MODEL") or DEFAULT_SUMMARY_MODEL,
    )


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: object


@dataclass(frozen=True)
class Turn:
    """One model response: its content blocks (appended to history unchanged) and summary."""

    content: Sequence[object]
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str | None = "end_turn"


class ModelClient(Protocol):
    async def turn(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_text: TextSink | None,
    ) -> Turn: ...


class Tools(Protocol):
    async def run(self, name: str, raw_args: object) -> ToolOutput: ...


class Sink(Protocol):
    """Where the reply streams to. ``reset`` clears what was streamed before a retry."""

    async def text(self, token: str) -> None: ...

    async def reset(self) -> None: ...

    async def tool(self, name: str, output: ToolOutput) -> None: ...


@dataclass
class Conversation:
    system: str
    summary_pass: bool = False  # the weekly review
    messages: list[Message] = field(default_factory=list)
    exempt: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Reply:
    text: str  # as shown, marks included
    retried: bool = False
    unlabelled: tuple[str, ...] = ()
    declined: bool = False


class DeclinedError(Exception):
    """The turn cannot be shown: a refusal or a tool call cut off by the token limit."""


@dataclass
class Loop:
    client: ModelClient
    tools: Tools
    settings: ChatSettings = field(default_factory=ChatSettings)

    async def respond(self, convo: Conversation, user_text: str, sink: Sink) -> Reply:
        start = len(convo.messages)
        convo.messages.append({"role": "user", "content": user_text})
        try:
            if convo.summary_pass:
                draft = await self._agent(convo, sink, stream=False)
                return await self._checked(convo, sink, self._summary_producer(convo, sink, draft))
            return await self._checked(convo, sink, self._agent_producer(convo, sink))
        except DeclinedError as exc:
            del convo.messages[start:]  # leave a history the API accepts
            await sink.reset()
            return Reply(str(exc), declined=True)

    # --- producing the text that is checked -----------------------------------------

    def _agent_producer(
        self, convo: Conversation, sink: Sink
    ) -> Callable[[str | None], Awaitable[str]]:
        async def produce(note: str | None) -> str:
            if note is not None:
                convo.messages.append({"role": "user", "content": note})
            return await self._agent(convo, sink, stream=True)

        return produce

    def _summary_producer(
        self, convo: Conversation, sink: Sink, draft: str
    ) -> Callable[[str | None], Awaitable[str]]:
        messages: list[Message] = [{"role": "user", "content": SUMMARY_NOTE + draft}]

        async def produce(note: str | None) -> str:
            if note is not None:
                messages.append({"role": "user", "content": note})
            turn = await self._turn(
                self.settings.summary_model, convo.system, messages, [], sink.text
            )
            messages.append({"role": "assistant", "content": list(turn.content)})
            return turn.text

        return produce

    async def _checked(
        self, convo: Conversation, sink: Sink, produce: Callable[[str | None], Awaitable[str]]
    ) -> Reply:
        text = await produce(None)
        first = check_layers(text, convo.exempt)
        if first.ok:
            return Reply(text)
        await sink.reset()
        note = RETRY_NOTE + "\n".join(f"- {fragment}" for fragment in first.unlabelled)
        text = await produce(note)
        second = check_layers(text, convo.exempt)
        shown = text if second.ok else mark_unlabelled(text, convo.exempt)
        return Reply(shown, retried=True, unlabelled=second.unlabelled)

    # --- the tool loop ------------------------------------------------------------------

    async def _agent(self, convo: Conversation, sink: Sink, *, stream: bool) -> str:
        for _ in range(MAX_TOOL_ROUNDS):
            on_text = sink.text if stream else None
            turn = await self._turn(
                self.settings.model, convo.system, convo.messages, api_tools(), on_text
            )
            convo.messages.append({"role": "assistant", "content": list(turn.content)})
            if turn.stop_reason == "pause_turn":
                continue
            if not turn.tool_calls:
                return turn.text
            if turn.stop_reason == "max_tokens":
                raise DeclinedError("The reply was cut off before a tool call was complete.")
            convo.messages.append(
                {"role": "user", "content": await self._run_tools(convo, sink, turn)}
            )
        raise DeclinedError(f"Stopped after {MAX_TOOL_ROUNDS} rounds of tool calls.")

    async def _turn(
        self,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_text: TextSink | None,
    ) -> Turn:
        turn = await self.client.turn(
            model=model, system=system, messages=messages, tools=tools, on_text=on_text
        )
        if turn.stop_reason == "refusal":
            raise DeclinedError("The model declined this request.")
        return turn

    async def _run_tools(self, convo: Conversation, sink: Sink, turn: Turn) -> list[Message]:
        outputs = await asyncio.gather(*(self.tools.run(c.name, c.input) for c in turn.tool_calls))
        results: list[Message] = []
        for call, out in zip(turn.tool_calls, outputs, strict=True):
            convo.exempt.extend(out.exempt)
            await sink.tool(call.name, out)
            result: Message = {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": out.content,
            }
            if out.is_error:
                result["is_error"] = True
            results.append(result)
        return results


# --- the Anthropic SDK as the model client ---------------------------------------------


class AnthropicModel:
    """Streams one turn with the SDK: adaptive thinking, server-side refusal fallback,
    automatic prompt caching. Tool inputs stream eagerly and are validated by the
    tool box before anything runs."""

    def __init__(self, client: Any, settings: ChatSettings) -> None:
        self.client = client  # anthropic.AsyncAnthropic; Any: the external-API boundary
        self.settings = settings

    async def turn(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_text: TextSink | None,
    ) -> Turn:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": self.settings.max_tokens,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.settings.effort},
            "cache_control": {"type": "ephemeral"},
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }
        if tools:
            params["tools"] = tools
        for attempt in range(JSON_RETRIES + 1):
            try:
                message = await self._stream(params, on_text)
                break
            except ValueError:
                # tool input JSON the SDK could not parse at all (eager streaming): the
                # tool_use block never completed, so the turn is re-issued. API errors
                # are not ValueError and propagate.
                if attempt == JSON_RETRIES:
                    raise
        return to_turn(message)

    async def _stream(self, params: dict[str, Any], on_text: TextSink | None) -> Any:
        async with self.client.beta.messages.stream(**params) as stream:
            async for event in stream:
                if event.type == "text" and on_text is not None:
                    await on_text(event.text)
            return await stream.get_final_message()


def to_turn(message: Any) -> Turn:
    """An SDK message as a ``Turn``; the content blocks are kept as they came."""
    content = list(message.content)
    text = "".join(b.text for b in content if b.type == "text")
    calls = tuple(ToolCall(b.id, b.name, b.input) for b in content if b.type == "tool_use")
    return Turn(content, text, calls, message.stop_reason)
