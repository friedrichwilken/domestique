# Design

## Context

See proposal.md. The console (change `web-console`) exposes JSON routes; the claims MCP server exposes seven tools, three of them gated by the human token; `skills/*.md` describe inputs, order of reasoning and output shape for each reasoning step and quote the hard rules from CLAUDE.md.

## Goals / Non-Goals

**Goals:** a chat an athlete can open in a browser; the model as a client with a short allow-list; source layers enforced on the way out, not only requested on the way in.
**Non-Goals:** letting the model change state that a human is meant to decide; a general assistant; any route from the model to the database.

## Decisions

- **Chainlit as the front end, Anthropic SDK as the loop.** Chainlit gives streaming, history and a browser UI for free and is Python, like the rest. The agent loop is written against the SDK's tool runner so the allow-list is ours, not the framework's. Alternative: a chat page inside the console. Rejected: it would put the model dependency into the deterministic service.
- **Modes are files, not prompts in code.** `skills/<mode>.md` is read at startup and used verbatim as the system prompt, prefixed only with the date, timezone and athlete id from config. Editing a mode means editing a Markdown file under review; no prompt text lives in Python.
- **Tool allow-list is a static tuple.** The model sees exactly: `console_claims`, `console_day`, `console_questions` (HTTP GETs against the `app` service) and `query_claims`, `propose_claim`, `attach_evidence` (MCP). Adding a tool is a code change with a test that the gated names are absent.
- **Response check as a pure function.** `check_layers(text) -> Checked` parses bullets and inline statements, requires one of `(your data shows)`, `(you told me)`, `(the literature says)` (the same labels `output.comments` renders), and returns the unlabelled fragments. The chat sends them back once with the instruction to label; on a second failure the fragments are shown marked "unlabelled". The rails wording and question text, which arrive from tools, are exempt and passed through unchanged.
- **Model choice from CLAUDE.md.** `claude-opus-5-5` for the reasoning turns, a cheaper model for the weekly-review summary pass, both set in one place and overridable by `DOMESTIQUE_CHAT_MODEL`.
- **Conversation storage in a named volume.** Chainlit's data layer writes to `/data` inside the container, a named compose volume. Nothing from it is read by the console or the loop.
- **Non-root images with a uid build argument.** `ARG UID=1000`, `USER ${UID}`. On the Mac the config mount is readable regardless; on Linux the athlete passes `--build-arg UID=$(id -u)`. Applied to both images in this change.

## Risks / Trade-offs

- Chainlit's release cadence is fast; pinned with an upper bound, reviewed on upgrade.
- The layer check is textual and can be fooled by a label on a wrong statement. It enforces the habit, not the truth; the loop enforces the truth.
- The model can propose junk claims. Accepted: candidates cost nothing until a human confirms them, and the review list in the console shows who proposed what.
