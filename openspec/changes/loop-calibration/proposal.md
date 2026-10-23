# Proposal

## Why

The first replay over the synthetic season found two defects in the loop (cornerstone 3). Only the winning claim is ever scored, so a rival claim can take over only when the winner keeps missing, which makes learning fragile: the planted effect was recovered on about 16 of 20 random seeds. And the always-hit flag fires on well-calibrated claims, because a correctly sized range hits roughly 85–90% of the time and ten straight hits are common; it switched off a correct prior in the fixture season.

## What Changes

- Every applicable claim produces a shadow prediction and is scored; the winner's prediction is the one reported and the one stored as the official prediction, the others are stored as shadows.
- The always-hit flag is replaced by a range-calibration check: a claim is flagged as uninformative when, over at least ten scored predictions, the mean absolute error is below a third of its mean half-range; a claim is flagged as overconfident when its hit rate falls below 60%.
- The replay reports both flags per claim.

Out of scope: changing confidence step sizes; the model step.

## Capabilities

### New Capabilities
- none

### Modified Capabilities
- `prediction-loop`: shadow scoring for all applicable claims; the uninformative-range rule replaces the always-hit rule.

## Impact

`src/domestique/loop/predict.py`, `score.py`, `store.py`; `src/domestique/claims/rules.py`; a migration adding a shadow marker to predictions; `evals/replay.py` report; tests.
