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

## Nutrition and comments

Migration `0003_nutrition_and_comments.sql` (change `comments-and-nutrition`).
Absent upstream values stay NULL, never zero.

- `activities` gains `kcal` (energy expended, `calories`), `carbs_used_g`
  (`carbs_used`) and `carbs_ingested_g` (`carbs_ingested`), all as the
  platform reports them.
- `wellness` gains `kcal_consumed` (`kcalConsumed`), `carbs_g`
  (`carbohydrates`), `protein_g` (`protein`), `fat_g` (`fatTotal`),
  `hydration_ml` (`hydrationVolume`) and `hydration` (the rating).
- Activity comments go into the existing `subjective` table, one row per
  upstream comment, which gains `source, external_id, author_id, author_name,
  start_index, end_index, deleted, is_system`, unique on
  `(athlete_id, source, external_id)` so edits update in place. The comment
  text is stored unmodified in `answer`; `tags` holds `comment`, plus `fuel`
  when it carries a `#fuel` line or `system` when the system wrote it.
  `start_index`/`end_index` are the stream indices the comment is pinned to.
- `activity_intake(activity_id, fluid_ml, carbs_g, kcal, platform_carbs_g,
  carbs_differ, comment_external_id, updated_at)`: the ride's intake from the
  latest live athlete comment with a `#fuel` tag. The tag's carbohydrate wins;
  the platform's value at reconcile time stays in `platform_carbs_g` and
  `carbs_differ` flags a disagreement. No tag, no row.
- View `activity_nutrition`: per activity, energy expended, carbohydrate used,
  effective carbohydrate ingested with `carbs_source` (`tag` or `platform`),
  the platform value, fluid and energy ingested.
