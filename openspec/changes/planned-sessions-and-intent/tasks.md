# Tasks

## 1. Planned sessions

- [x] 1.1 Ingest planned workouts from the intervals.icu events API into `planned_sessions`; test: idempotent re-run on a fixture week with a double day
- [x] 1.2 Implement pairing by local date, sport and start-time proximity; test: double-day and unpaired scenarios

## 2. Intent layer

- [x] 2.1 Pydantic schemas and loader for `$DOMESTIQUE_HOME/intent/*.yaml` via `domestique.config`; test: missing `set_by` fails naming file and field
- [x] 2.2 Rails registry in `src/domestique/rails/` with joint-pain, HRV floor, ramp ceiling, illness; test: one triggering and one quiet fixture per rail
- [x] 2.3 Override append function; test: existing entries unchanged, new entry carries the prediction

## 3. Plan vs execution

- [x] 3.1 `plan_vs_execution(date)` join; test: paired double day returns two rows with both sides
- [x] 3.2 Overshoot detection on work intervals with configurable margin producing a question for the athlete; test: sweet-spot text vs VO2 execution yields a question with both numbers and no judgement

## 4. Follow-ups (left open by the first implementation)

- [ ] 4.1 Constraint-vs-claim conflict report: when an active claim and a constraint address the same subject tag, return the constraint and list the claim as conflicting; test: observed-tolerance-vs-stated-constraint scenario
- [ ] 4.2 `DayData` loader from the database and a `python -m domestique.rails --date` entry that evaluates all rails for a day; test: loader against the compose database
- [ ] 4.3 `plan_vs_execution` CLI and the overshoot margin read from config; test: margin from config overrides the default
