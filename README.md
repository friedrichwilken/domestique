# domestique

A training-analysis assistant for endurance athletes. Named after the rider
who works for the leader and never takes the win: the athlete stays in
charge, the system does the work around them.

Status: planning scaffold, 2026-10-23. No implementation yet.
[DESIGN.md](DESIGN.md) is the source of truth; `tasks/` holds the build
order.

## Configuration

All athlete-specific configuration lives outside the repo in
`$DOMESTIQUE_HOME` (default `~/.config/domestique`): `config.yaml` plus an
`intent/` directory. Copy `examples/` there and edit. Secrets are
environment variables, see `.env.example`. Nothing personal is ever read
from the repository.

## Layout

| Path | What |
|---|---|
| `DESIGN.md` | The five cornerstones, precedence rules, what stays human |
| `docs/schema.md` | Data-plane and claims tables |
| `docs/stack.md` | Technical stack and runtime options |
| `examples/` | Example `config.yaml` and intent files for a synthetic athlete |
| `skills/` | Agent workflows as markdown (debrief, readiness, review, plan-vs-execution) |
| `tasks/` | Implementation task specs, numbered, one per PR |
| `src/domestique/` | Python package, one subpackage per cornerstone |
| `mcp/claims/` | The athlete-model MCP server |
| `migrations/` | SQL migrations for the data plane |
| `evals/` | Replay harness over historical seasons |
