# Proposal

## Why

This is the project: cornerstones 2 and 3. Without a claims store with provenance, the assistant speaks textbook priors in the voice of observations. Without a prediction loop, the store is a notebook that only grows. Mirrors `tasks/003-claims-store-and-prediction-loop.md`.

## What Changes

- Claims, claim history (append-only), evidence, predictions, outcomes and questions tables.
- An MCP server over the claims store with a human-gated confirm/retire tool.
- Rule-based prediction for a planned session from active claims, and a nightly scoring job that adjusts confidence and drafts questions.
- A synthetic seed of ~20 claims across the three source layers.

Out of scope: the model step that proposes claims in prose (a later change); the planner.

## Capabilities

### New Capabilities
- `athlete-claims`: claims about the athlete carry a source layer, confidence, evidence and an auditable history; precedence and gating are enforced by the store.
- `prediction-loop`: every planned session yields predictions that cite claims; outcomes score them and move confidence by a documented rule.

### Modified Capabilities
- none

## Impact

`migrations/0002_claims.sql`, `src/domestique/claims/`, `src/domestique/loop/`, `mcp/claims/`, `evals/fixtures/claims_seed.yaml`.
