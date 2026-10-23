# 003 — claims store, claims MCP, prediction and outcome loop

**Depends on:** 001, 002. **Blocks:** 004, 005.

## Why

This is the project. Cornerstones 2 and 3.

## Deliverables

1. `migrations/0002_claims.sql`: `claims`, `claim_history`, `evidence`,
   `predictions`, `outcomes`, `questions` per `docs/schema.md`.
2. `mcp/claims/`: MCP server with `query_claims(filter)`,
   `propose_claim(text, source_layer, evidence[])` (creates status
   `candidate`), `attach_evidence(claim_id, ...)`,
   `confirm_or_retire(claim_id, status, reason)` (human-gated: refuses
   unless called with a human token).
3. `src/domestique/loop/predict.py`: for a planned session, produce
   predictions for watts-at-HR, peak HR, next-morning HRV and sleep hours
   from active claims (rule-based first; the model step comes in 005).
4. `src/domestique/loop/score.py`: nightly job that fills `outcomes`,
   adjusts confidence by a documented rule, and writes `questions` rows
   when a miss co-occurs with a plan-vs-execution flag.
5. Seed file `evals/fixtures/claims_seed.yaml` with ~20 example claims
   across the three source layers (synthetic athlete).
6. Tests: a miss lowers confidence; a prior with N confirmed predictions
   becomes observed; a retired claim never feeds a prediction.
