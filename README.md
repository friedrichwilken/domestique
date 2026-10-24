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

## Running

- `just ingest --from 2026-09-01`: activities, wellness, and the comments and `#fuel` intake on those activities (`--no-comments` skips them).
- `just comments --from 2026-09-01`: comments and `#fuel` intake only, for activities already ingested.
- `just seed --file evals/priors.yaml`: load a seed file into the claims store; claims stay candidates until confirmed through the claims MCP (`--activate` skips that gate).
- `just web`: the web console, see below.

## Web console

`just web` starts the web console beside the database at
`http://127.0.0.1:8000/claims`: every claim with its confidence, hit rate,
error against its pre-registered range and calibration flags, a strip of
predicted range against observed value per claim, and stated confidence
against observed hit rate. `/claims.json` has the same data. `/day` shows
today's rails, plan versus execution and open questions; candidate claims
are confirmed or retired from the claims page with the human token. It binds to
localhost only and mounts `$DOMESTIQUE_HOME` read-only; the page is full of
personal data, so it is never published. `just eval --html evals/out/claims.html`
writes the same page for the synthetic fixture season. Details in
[docs/stack.md](docs/stack.md#web-console).

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
