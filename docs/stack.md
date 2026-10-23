# Stack

- **Language**: Python 3.12, `uv`, `ruff`, `pytest`.
- **Store**: Postgres 16 + TimescaleDB. Migrations in `migrations/` (plain
  SQL, numbered).
- **Ingestion**: one worker per source (intervals.icu, TrainingPeaks,
  wellness via intervals.icu), run as CronJobs. Thin clients over the
  public intervals.icu and TrainingPeaks APIs.
- **Derived metrics**: pure functions in `src/domestique/metrics/`, SQL
  views for the cheap ones. No model in this path.
- **Claims MCP** (`mcp/claims/`): `query_claims`, `propose_claim`,
  `attach_evidence`, `confirm_or_retire` (human-gated).
- **Rails**: `src/domestique/rails/`, pure Python rules with tests,
  evaluated before any session is emitted.
- **Planner**: `src/domestique/planner/`, templates + session library +
  constraint check; emits TrainingPeaks structure JSON.
- **Agent runtime**: Anthropic SDK tool runner, scheduled as Kubernetes
  CronJobs (nightly debrief, morning readiness, weekly review), MCP servers
  attached. Managed Agents with scheduled deployments and per-athlete
  memory stores is the alternative once the claims MCP and rails are
  stable. Reasoning steps on `claude-opus-5-5`; summaries and the
  one-question channel on a cheaper model.
- **Configuration**: `$DOMESTIQUE_HOME/config.yaml` and
  `$DOMESTIQUE_HOME/intent/*.yaml`, loaded by `src/domestique/config.py`.
  Secrets from the environment. The repo ships `examples/` only.
- **Skills**: markdown in `skills/`, one per workflow.
- **Interfaces**: Telegram bot first (one question per ride, morning
  brief). A weekly markdown summary plus the questions queue, shareable with anyone the athlete chooses.
- **Evals**: `evals/replay.py` over a season of fixture data; headline
  metric is prediction error per metric over time.
