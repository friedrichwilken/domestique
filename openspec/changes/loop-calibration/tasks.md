# Tasks

## 1. Shadow scoring

- [x] 1.1 Migration: predictions keyed by (session, metric, claim) with `official` and a partial unique index; stores updated; test: reported-prediction-is-official scenario
- [x] 1.2 Predictor records a prediction per applicable claim and marks the winner; scorer scores and adjusts all; test: rival-takes-over scenario in memory

## 2. Calibration flags

- [x] 2.1 Replace the always-hit rule in `rules.py` with the uninformative-range and overconfident rules, tracking mean absolute error and mean half-range per claim; test: wide-range, well-calibrated and overconfident scenarios
- [x] 2.2 Replay report lists both flags per claim; re-run the planted-effect check over 20 seeds and record the pass count in the PR; test: planted effect holds on the committed seed with the loop on
