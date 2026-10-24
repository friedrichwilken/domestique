# Design

## Context

See proposal.md. The data exists: `claims` (confidence, status, flags, calibration sums), `predictions` (low, high, expected, official, claim_id), `outcomes` (actual, error), `planned_sessions`, `questions`; `rails.load.load_day` and `analysis.plan_vs_execution` produce per-day results; `replay.report` already reduces a `RunResult` to per-claim rows.

## Goals / Non-Goals

**Goals:** one process that shows everything the deterministic plane knows; a page that makes error visible per claim; a human gate that does not require an MCP client.
**Non-Goals:** interactivity beyond forms; dashboards for raw training data (intervals.icu already has those); anything an LLM does.

## Decisions

- **Server-rendered HTML with inline SVG, no client framework.** Pages are strings produced by pure functions over dataclasses, so the tests compare structure (element counts, labels, marker shapes) without a browser. Alternative: a JavaScript charting library. Rejected: it moves the testable part into the browser and adds a CDN dependency to a page full of personal data.
- **Framework: FastAPI with Jinja2 templates, served by uvicorn.** Typed, small, and the JSON side comes for free. The templates hold layout only; every number is computed in `web/queries.py` and `web/charts.py`, which the tests exercise directly.
- **One `ReportData` input for both sources.** `queries.from_db(conn, athlete_id)` and `queries.from_replay(result)` both build the same dataclass; the renderer never knows which. This is what lets the replay write the fixture page and gives the repo a screenshot without exposing real data.
- **Calibration strip encodes error, not just hit or miss.** Per prediction the band is `[low, high]`, the marker is `actual`; the distance from marker to band is the error the athlete asked to see. Misses use a hollow marker and a text label, not colour alone. Shadow predictions are drawn lighter and can be hidden by a query parameter, since the claim's own calibration counts them.
- **Confidence against hit rate, one marker per claim, size by scored count.** Only claims with at least one scored prediction appear; claims with fewer than ten sit below the diagonal band and are labelled "early". No binned reliability diagram: at a dozen claims the bins are empty.
- **Human gate as a POST with the token in the form body.** Same validation as the MCP tool (`confirm_or_retire`, `clear_flags`), same history row written. Never a GET, never the token in a query string or cookie. The page shows the history after the action.
- **Container binds 127.0.0.1 only; config mounted read-only.** `DOMESTIQUE_HOME=/config`, database URL points at the `db` service. Secrets come from the environment of the container, never from the image. The image is built from the repo and contains no athlete data.
- **Dates and timezone from config.** The day view defaults to today in the athlete's configured timezone.

## Risks / Trade-offs

- Two web dependencies (fastapi, jinja2, uvicorn) widen the install. Accepted; they are pinned with upper bounds like the rest.
- A form with a shared token on localhost is weak authentication. Accepted for a single-athlete service bound to loopback; the proposal names this as out of scope.
- The strip gets crowded past ~60 predictions per claim. The page shows the last 60 and says so; the JSON view has all of them.
