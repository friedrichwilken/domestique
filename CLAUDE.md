# domestique — Claude instructions

Training-analysis assistant for endurance athletes. Five cornerstones, see [DESIGN.md](DESIGN.md).
Read it before any design decision.

## The one rule

**Every recommendation carries its source layer.** `observed` (this
athlete's data), `stated` (the athlete said so), or `prior` (textbook).
Precedence is observed > stated > prior, and the intent layer beats all
three. A prior spoken in the voice of an observation is the failure mode
this project exists to remove. If a claim has no source layer, it does not
exist.

## What stays human

- Nothing writes a plan to TrainingPeaks without a human approving it.
- Pain, illness, injury: rails stop the plan and produce referral wording,
  never advice.
- The intent behind a prescribed session is asked, never inferred from workout text.

## Planning vs implementing

- Planning sessions change `DESIGN.md`, `docs/`, and write task specs in
  `tasks/NNN-name.md`. They do not write code.
- Implementation sessions take exactly one task file and build it. The task
  body is the contract; if ambiguous, stop and report, do not widen scope.
- Tests over prompts: derived metrics, rails and the planner are code with
  unit tests. Prompts only reason over their output.

## Stack

Python 3.12, Postgres + TimescaleDB, Anthropic SDK (`claude-opus-5-5` for
reasoning steps, cheaper model for summaries), MCP servers for
TrainingPeaks, intervals.icu and the claims store. Details in
[docs/stack.md](docs/stack.md).

## Athlete data and configuration

This repo is public. Real athlete data, ids, names and personal
constraints never enter it. Configuration and intent files live in
`$DOMESTIQUE_HOME` on the athlete's machine (`examples/` shows the shape
with a synthetic athlete). Fixtures in `evals/fixtures/` are synthetic.
Before committing, grep for ids, names and anything that reads like one
person's medical or life situation.
