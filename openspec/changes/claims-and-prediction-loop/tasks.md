# Tasks

## 1. Store

- [x] 1.1 `migrations/0002_claims.sql` with enum source layer, confidence check constraints by layer, append-only trigger on claim_history; test: migration applies, history edit is rejected
- [x] 1.2 Repository layer with Postgres and in-memory implementations of query, propose, attach_evidence, confirm_or_retire; test: proposal without layer rejected, candidate status on propose
- [x] 1.3 Confidence rules module (hit, miss, cap, retire, promote); test: one test per clause

- [x] 1.4 Add `horizon` to the claims schema, repositories, rules and MCP; caps 0.7/0.5 for week/season, no promotion for season, refused-promotion history row; test: season-with-hits and week-promoted scenarios
- [x] 1.5 Always-hit flag in the rules module (≥10 scored, >95% hits); test: eleventh-hit scenario
- [x] 1.6 Add a horizon to every claim in `evals/fixtures/claims_seed.yaml`; test: seed validates

## 2. MCP

- [x] 2.1 Stdio MCP server exposing the four tools, confirm_or_retire gated by `DOMESTIQUE_HUMAN_TOKEN`; test: refused without token
- [x] 2.2 `mcp/claims/README.md` with an mcp.json example

## 3. Loop

- [ ] 3.1 Rule-based `predict(planned_session)` producing cited predictions with ranges; test: no-claim metric yields no prediction and a reported gap
- [ ] 3.2 `score(session)` nightly job writing outcomes once and applying the confidence rule; test: scored-once and miss-lowers-confidence scenarios
- [ ] 3.3 Overshoot-miss path creating a question for the athlete and leaving claims unchanged; test: overshoot scenario

## 4. Seed

- [x] 4.1 `evals/fixtures/claims_seed.yaml` with ~20 synthetic claims across layers and a loader; test: seed loads and validates
