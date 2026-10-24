# Proposal

## Why

The system now records more than it shows. Every claim carries a confidence, every scored prediction carries a pre-registered range and an observed value, the rails and the plan-vs-execution join produce per-day results, and the only ways to see any of it are a text replay report and an MCP query tool. The loop is honest on disk and invisible on screen. An athlete, or anyone they share the page with, needs to see which claims are tight, which are vague, and where stated confidence disagrees with observed hit rate. That picture is also the one that answers the "an athlete model is unlearnable at n=1" critique with data instead of argument.

All deterministic parts should also run as one service next to the database, so that running the system does not mean running a dozen `just` recipes by hand. The web console is that service. It serves cornerstones 2 and 3 (claims and the loop) first and cornerstone 4 (intent and rails) second.

## What Changes

- A new `domestique.web` package: a small HTTP application with server-rendered HTML pages and the same data as JSON. No JavaScript framework; charts are inline SVG drawn in Python so that pages are testable as strings and render with no network access.
- Page one, the **claims report**: a table of claims with status, source layer, horizon, confidence, scored count, hit rate, mean error as a share of the range half-width and the two calibration flags; a **calibration strip** per claim (predicted range as a band, observed value as a marker, misses marked by shape as well as colour); and a **confidence-versus-outcome** chart with one marker per claim and the diagonal drawn.
- Page two, the **day view**: rails results, plan-vs-execution rows and open questions for one date, from the existing loaders and joins.
- The **human gate** as a form: confirm or retire a candidate claim, and clear its flags, with `DOMESTIQUE_HUMAN_TOKEN` entered in the form. The same rule as the MCP tool, a second door to it.
- A `Dockerfile` and an `app` service in `docker-compose.yml` binding to the loopback interface only, with `$DOMESTIQUE_HOME` mounted read-only. `just web` runs it.
- The renderer accepts the replay's result as well as the database, so `just eval` can write the same page from synthetic data.

Out of scope: a chat interface over the language model (a separate change; the console holds no LLM dependency), scheduling ingest from the container, editing intent files from the browser (they stay files under version control on the athlete's machine), authentication beyond the human token (the service binds to localhost), and any trend line of confidence over time (it would only redraw the adjustment rules).

## Capabilities

### New Capabilities
- `web-console`: HTML and JSON views over claims, predictions, rails, plan-vs-execution and questions; the human gate as a form; the service container.

### Modified Capabilities
- `replay-eval`: the replay can write the claims report page for the fixture season.

## Impact

New `src/domestique/web/` (app, queries, SVG, templates), `Dockerfile`, `docker-compose.yml`, `justfile`, `pyproject.toml` (web dependencies), `docs/stack.md`, `README.md`; `evals/replay.py` gains `--html`. No schema change.
