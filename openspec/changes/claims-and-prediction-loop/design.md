# Design

## Context

See proposal.md. Depends on `data-plane` and `planned-sessions-and-intent`. Schema in `docs/schema.md`.

## Goals / Non-Goals

**Goals:** a store whose invariants (layer, caps, append-only history, human gating) are enforced in the database and the repository layer, and a loop that works rule-based before any model is involved.
**Non-Goals:** natural-language claim proposals; a UI.

## Decisions

- **Invariants in Postgres where possible** (enum for source layer, trigger rejecting history edits, check constraints on confidence caps) and mirrored in an in-memory repository for tests. Alternative: enforce only in Python. Rejected: the MCP server is not the only writer.
- **Human gating by a shared token in an environment variable** for v1. Alternative: per-user auth. Deferred until there is more than one human.
- **Rule-based predictor first.** Predictions are simple functions of claims (for example watts-at-HR from the last three observed values with a ±5% range). The model step that proposes new claims in prose is a separate change so the loop can be evaluated without it.
- **Confidence rule**: +0.1 hit, −0.15 miss, caps 0.95/0.8/0.6 by layer, retire under 0.1, promote prior after five consecutive hits. Asymmetric on purpose: a wrong claim should die faster than a right one grows.

## Risks / Trade-offs

- Ranges that are too wide make every prediction a hit. Mitigation: the replay eval reports hit rate alongside error; a hit rate near 100% is itself a finding.
- Claims about sleep depend on Garmin's weak sleep staging. Store total sleep time only.
