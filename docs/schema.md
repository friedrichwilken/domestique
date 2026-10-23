# Schema (draft)

Postgres + TimescaleDB. All timestamps UTC with the athlete's local offset
stored alongside. `athlete_id` on every table; single-athlete deployments
just use one.

## Data plane

- `activities(id, athlete_id, source, external_id, start_local, start_utc, sport, name, moving_s, avg_w, np_w, avg_hr, max_hr, avg_cad, ftp_at_ride, load, if, ef, decoupling, lr_balance, raw jsonb)`
- `activity_streams(activity_id, t_s, watts, hr, cadence, lr, temp)` — hypertable
- `activity_intervals(id, activity_id, idx, kind, start_s, dur_s, avg_w, avg_hr, max_hr, avg_cad, lr_balance)`
- `planned_sessions(id, athlete_id, source, external_id, date, title, description, structure jsonb, planned_tss, planned_if, intent_ref)`
- `wellness(athlete_id, date, hrv, rhr, sleep_s, sleep_score, weight, ctl, atl, source, raw jsonb)`
- `ftp_history(athlete_id, valid_from, ftp_w, source)`
- `subjective(id, athlete_id, ts, activity_id?, rpe, feel, answer text, tags text[])`
- `context(athlete_id, date, kind, value)` — work day, med day, travel, race, illness
- `tests(id, athlete_id, date, kind, result jsonb, activity_id?)` — ground truth

Derived metrics are SQL views or pure functions in `src/domestique/metrics/`,
unit-tested against fixture rides.

## Athlete model

- `claims(id, athlete_id, text, source_layer enum(observed,stated,prior), horizon enum(day,week,season), confidence numeric, status enum(active,retired,candidate), created_at, last_tested_at, created_by, hit_streak, scored, hits, always_hit)`
- `claim_history(claim_id, ts, confidence, status, reason, by)` — append-only
- `evidence(id, claim_id, kind enum(activity,interval,wellness,statement,reference,query), ref text, note)`

## Prediction loop

- `predictions(id, planned_session_id, metric, expected numeric, low numeric, high numeric, claim_ids uuid[], made_at)`
- `outcomes(prediction_id, actual numeric, error numeric, scored_at)`
- `questions(id, athlete_id, for enum(athlete,reviewer), text, context jsonb, status, created_at, answered_at, answer)`

## Intent

Files in `$DOMESTIQUE_HOME/intent/*.yaml` on the athlete's machine, loaded read-only at run time. Overrides are
appended by the system with the prediction they overruled.
