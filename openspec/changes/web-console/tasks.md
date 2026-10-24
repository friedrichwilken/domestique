# Tasks

## 1. Service skeleton

- [ ] 1.1 `src/domestique/web/` with a FastAPI app, config loaded via `domestique.config`, a `/healthz` route and a `/claims.json` route returning `ReportData` from the database; `web/queries.py` with `from_db`; test: `from_db` against the compose database with two seeded claims and three scored predictions (DSN-guarded), and `/healthz` through the test client
- [ ] 1.2 `Dockerfile`, `app` service in `docker-compose.yml` on `127.0.0.1:${DOMESTIQUE_WEB_PORT:-8000}` with `$DOMESTIQUE_HOME` mounted read-only at `/config`, `just web`; `docs/stack.md` and `README.md` gain a short section; test: `docker compose config` parses in CI (no build in CI)

## 2. Claims report page

- [ ] 2.1 `web/charts.py`: pure functions `claims_table(ReportData) -> list[Row]`, `calibration_strip(claim, predictions) -> str` (SVG) and `confidence_vs_hit_rate(ReportData) -> str` (SVG); test: a miss renders a hollow marker and a label, the strip truncates to the last 60 and says so, the scatter omits unscored claims and labels claims under ten scored as early
- [ ] 2.2 `/claims` HTML page from a Jinja2 template using 2.1, with a footer quoting DESIGN.md "What this cannot learn"; `?shadows=0` hides shadow markers; test: the page for a fixture `ReportData` contains one table row and one strip per claim
- [ ] 2.3 `queries.from_replay(RunResult) -> ReportData` and `evals/replay.py --html PATH` writing the page for the fixture season; test: `just eval --html` on the committed seed produces a page whose claim count matches the seed

## 3. Day view and human gate

- [ ] 3.1 `/day/{date}` page: rails results via `rails.load.load_day` and `rails.registry.evaluate`, plan-vs-execution rows via `analysis.plan_vs_execution`, open questions; default date is today in the configured timezone; test: a fixture day with one triggered rail and one overshoot question renders both wordings unchanged
- [ ] 3.2 Human gate: `POST /claims/{id}/decide` (status, reason, token) and `POST /claims/{id}/clear-flags` through the Postgres `ClaimsStore`; a wrong token returns 403 and writes nothing; test: correct token confirms a candidate and the history row carries `by`; wrong token leaves the claim unchanged
