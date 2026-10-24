# Proposal

## Why

The deterministic plane now runs as one service (change `web-console`) and the four reasoning steps exist as instruction files under `skills/`, but the only way to run a reasoning step is to open Claude Code with the MCP servers. An athlete without a developer setup cannot use the system at all. This change adds the conversational layer as its own service, so that the language model is one more client of the console and never part of it. It serves cornerstones 2 and 3 as the voice of the model, and the "Interfaces" section of DESIGN.md.

## What Changes

- A `chat` service, built on Chainlit, running the agent loop with the Anthropic SDK. Four modes, one per file in `skills/`: post-ride debrief, morning readiness, weekly review, plan versus execution. The skill file is the system prompt of its mode, loaded verbatim at startup.
- The model's tools are the console's JSON routes (claims, day view, questions) and the ungated tools of the claims MCP server (`query_claims`, `propose_claim`, `attach_evidence`). The gated tools (`confirm_or_retire`, `add_binding`, `clear_flags`) are not exposed; the model can propose, a human decides through the console's form.
- Every statement in a reply carries a source layer. A response check runs over the model's output before it is shown: a bullet without one of the three layer labels is sent back to the model once, and if it comes back unlabelled it is shown with a visible "unlabelled" mark rather than silently passed.
- Conversation history lives in the chat service's own volume. Athlete state never does; claims, intent and predictions stay in Postgres behind the gate.
- The chat container runs as a non-root user (uid build argument), since it is the one service that talks to the internet. The same argument is applied to the `app` image.
- Secrets: `ANTHROPIC_API_KEY` from the environment only.

Out of scope: the one-question-after-each-ride channel (Telegram or similar). It will use the same console routes and the same response check and gets its own change, `ride-question-channel`, once this one is in. Also out of scope: fine-tuning, embeddings or retrieval over documents; multi-athlete tenancy.

## Capabilities

### New Capabilities
- `chat-layer`: the Chainlit service, mode prompts from `skills/`, the tool allow-list, the source-layer response check, the non-root images.

### Modified Capabilities
- `web-console`: `/questions.json` and `/day/{date}.json` routes so the model reads the day view without HTML.

## Impact

New `src/domestique/chat/` (app, tools, response check, modes), `chat/Dockerfile`, `chat` service in `docker-compose.yml`, `pyproject.toml` optional dependency group `chat` (chainlit, anthropic already present), `docs/stack.md`, `README.md`, `DESIGN.md` "Services". No schema change.
