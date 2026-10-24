# Stack

- **Language**: Python 3.12, `uv`, `ruff`, `pytest`.
- **Store**: Postgres 16 + TimescaleDB. Migrations in `migrations/` (plain
  SQL, numbered).
- **Ingestion**: intervals.icu only for now (executed activities, planned
  workouts from its events API,
  wellness via intervals.icu), run as CronJobs. Thin clients over the
  public intervals.icu API. Other platforms are a later change.
- **Derived metrics**: pure functions in `src/domestique/metrics/`, SQL
  views for the cheap ones. No model in this path.
- **Claims MCP** (`mcp/claims/`): `query_claims`, `propose_claim`,
  `attach_evidence`, `add_binding` (human-gated unless the claim is a
  candidate), `confirm_or_retire` (human-gated).
- **Rails**: `src/domestique/rails/`, pure Python rules with tests,
  evaluated before any session is emitted.
- **Planner**: `src/domestique/planner/`, templates + session library +
  constraint check; emits intervals.icu workout structure.
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

## Web console

`domestique.web` (FastAPI, Jinja2 templates, uvicorn) serves what the
deterministic plane knows. Every number on a page is computed in
`web/queries.py` and `web/charts.py`; templates only lay it out, and charts
are inline SVG drawn in Python, so the page needs no network access and no
client-side framework. It holds no language-model dependency.

- `/claims`: one row per claim (status, source layer, horizon, confidence,
  scored, hit rate, mean absolute error as a share of the range half-width,
  the uninformative and overconfident flags); a calibration strip per claim
  (each scored prediction's pre-registered range as a band, the observed
  value as a marker, misses hollow and labelled with their distance to the
  range, shadows lighter, `?shadows=0` hides them, the last 60 shown); stated
  confidence against observed hit rate, one marker per scored claim, with the
  diagonal drawn.
- `/claims.json`: the same data, every prediction. `/healthz`: liveness.
- Run: `just web` builds and starts the `app` service in
  `docker-compose.yml` next to `db`. It publishes on `127.0.0.1` only
  (`DOMESTIQUE_WEB_PORT`, default 8000), mounts `$DOMESTIQUE_HOME` read-only
  at `/config` and takes `ICU_API_KEY` and `DOMESTIQUE_HUMAN_TOKEN` from the
  host environment; the image holds no athlete data. Outside a container:
  `python -m domestique.web` (`DOMESTIQUE_WEB_HOST`, `DOMESTIQUE_WEB_PORT`).
- `just eval --html PATH` writes the same claims page for the fixture season.
- The page is full of personal data. It binds to localhost and is never
  published.
