# Proposal

## Why

Prediction error over time is the only number that says whether the athlete model is learning anything. A replay harness over a past season turns that into a repeatable eval for every prompt or rail change. Mirrors `tasks/004-replay-eval.md`.

## What Changes

- A day-by-day replay over a fixture season that only exposes data up to the current day, predicts the next session, and scores when the day passes.
- A synthetic 12-week season with a planted effect so the harness can show the loop discovering it.
- CSV and markdown output; `just eval` prints the headline number last.

Out of scope: replaying real athlete data in the repo; model-step evaluation.

## Capabilities

### New Capabilities
- `replay-eval`: the system's predictive accuracy over a season can be measured offline, without leakage of future data.

### Modified Capabilities
- none

## Impact

`evals/replay.py`, `evals/fixtures/season_a/`, justfile.
