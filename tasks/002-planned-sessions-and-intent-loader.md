# 002 — planned sessions from TrainingPeaks and the intent loader

**Depends on:** 001. **Blocks:** 003.

## Deliverables

1. `src/domestique/ingest/tp.py`: planned sessions (title, description,
   structure JSON, planned TSS/IF) into `planned_sessions`. Thin client over the
   TrainingPeaks API. Pair with executed activities by date
   and sport; store the pairing.
2. `src/domestique/intent/`: loader for `$DOMESTIQUE_HOME/intent/*.yaml` with schema
   validation; `rails` evaluated as pure functions over a day's data
   (`src/domestique/rails/`), each rail unit-tested with a triggering and
   a non-triggering fixture.
3. `plan_vs_execution(date)` function returning the join: planned
   intensity/HR text, executed NP/HR/IF, and a flag when executed intensity
   exceeds planned by more than a configured margin. This flag must never
   infer intent; it produces a `questions` row for the athlete.
