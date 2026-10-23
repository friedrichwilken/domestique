# Design

## Context

See proposal.md. The loop stores one prediction per session and metric with a unique index; `rules.adjust_with_notes` holds the always-hit rule; the replay drives both through in-memory stores.

## Goals / Non-Goals

**Goals:** learning that does not depend on the winner failing first; a flag that measures range width, not luck.
**Non-Goals:** retuning step sizes or horizon caps.

## Decisions

- **Shadow predictions as rows, not a side table.** The unique index becomes (session, metric, claim) with an `official` boolean and a partial unique index on official rows. Alternative: keep one row and score rivals in memory. Rejected: shadows need history for the review list.
- **Calibration via error-to-range ratio.** Mean absolute error below a third of the half-range means the range could be three times narrower and still hit; that is the definition of uninformative. Hit rate below 60% means the range is too narrow. Both need ten scored predictions, so a claim's first ten outcomes count without flagging.
- **Overconfident claims are penalised, not frozen.** A narrow range is a wrong claim about precision; it should lose confidence, and tightening is the athlete's job at review.

## Risks / Trade-offs

- Scoring every applicable claim multiplies writes by the number of rivals, which is small in practice.
- A claim can be both uninformative on one metric and fine on another; flags are per claim, so a claim should bind to one metric. The review list should say so when it does not.
