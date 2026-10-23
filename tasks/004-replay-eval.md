# 004 — replay eval harness

**Depends on:** 003.

## Deliverables

1. `evals/replay.py`: walk a fixture season day by day; at each day only
   data up to that day is visible; run predict for the next planned
   session; score when the day passes. Emit prediction error per metric
   over time as CSV and a one-page markdown summary.
2. A synthetic 12-week fixture season in `evals/fixtures/season_a/` with a
   known planted effect (e.g. evening intensity costs 1 h of sleep) so the
   harness can show the loop discovering it.
3. `just eval` runs it; the headline number is printed last.
