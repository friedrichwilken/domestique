# Proposal

## Why

Plan-versus-execution has to be a join between what was prescribed and what was ridden, not a guess, and the system must never infer the intent behind a prescription from workout text. This change brings planned sessions into the data plane (cornerstone 1), loads the intent layer (cornerstone 4) and evaluates safety rails as code. Mirrors `tasks/002-planned-sessions-and-intent-loader.md`.

## What Changes

- Ingest planned sessions from TrainingPeaks and pair them with executed activities.
- Load `intent/*.yaml` (goals, constraints, overrides, rails) with schema validation.
- Evaluate rails as pure functions over a day's data.
- A plan-vs-execution join that flags intensity overshoot and produces a question for the athlete instead of a conclusion.

Out of scope: writing anything back to TrainingPeaks; the planner; any model step.

## Capabilities

### New Capabilities
- `planned-session-ingestion`: prescribed sessions enter the data plane and are paired to executed activities.
- `intent-layer`: human decisions (goals, constraints, overrides, rails) are loaded, validated and take precedence over every other layer.
- `plan-vs-execution`: the join between prescribed and executed, with overshoot detection that asks rather than concludes.

### Modified Capabilities
- none

## Impact

New `src/domestique/ingest/tp.py`, `src/domestique/intent/`, `src/domestique/rails/`; `questions` rows (table defined in change `claims-and-prediction-loop`; until then the join returns question objects).
