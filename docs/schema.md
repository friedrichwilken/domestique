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

- `claims(id, athlete_id, text, source_layer enum(observed,stated,prior), horizon enum(day,week,season), confidence numeric, status enum(active,retired,candidate), created_at, last_tested_at, created_by, hit_streak, scored, hits, uninformative, overconfident, calib_scored, calib_hits, calib_abs_error, calib_half_range)`
- `claim_history(claim_id, ts, confidence, status, reason, by)` — append-only
- `evidence(id, claim_id, kind enum(activity,interval,wellness,statement,reference,query), ref text, note)`

## Prediction loop

- `predictions(id, planned_session_id, metric, expected numeric, low numeric, high numeric, claim_ids uuid[], made_at)`
- `outcomes(prediction_id, actual numeric, error numeric, scored_at)`
- `questions(id, athlete_id, for enum(athlete,reviewer), text, context jsonb, status, created_at, answered_at, answer)`

Migration `0005_loop.sql` (tasks 3.1-3.3): `predictions.planned_session_id` becomes
`bigint → planned_sessions(id)` (0002 had declared it uuid), predictions gain
`basis jsonb` (the pre-registered inputs: HR band, base value, rides, superseded
claims), `metric` is one of `watts_at_hr, peak_hr, hrv_next_morning, sleep_hours`,
and `(planned_session_id, metric)` is unique, so a session is predicted once.

Migration `0006_shadow_predictions.sql` (change `loop-calibration`): every applicable
claim gets its own prediction, so predictions gain `claim_id uuid → claims(id)` and
`official boolean`. Unique on `(planned_session_id, metric, claim_id)`, plus a partial
unique index on `(planned_session_id, metric) WHERE official`: one reported prediction
per session and metric, the rest are shadows, scored the same way. `claims` drops
`always_hit` and gains the calibration flags `uninformative` (mean absolute error under
a third of the mean half-range) and `overconfident` (hit rate under 60%), judged over
the window `calib_scored`, `calib_hits`, `calib_abs_error` and `calib_half_range`
(sums, in the metric's unit) once it holds ten outcomes; clearing the flags resets the
window. Rules in `src/domestique/claims/rules.py`.

- `claim_bindings(claim_id, metric, params jsonb, conditions jsonb, created_at)`: how a
  claim feeds a metric. `expected = base * (1 + change_pct/100) + offset`, range
  `expected -/+ (expected * range_pct/100 + range_abs)`; `rides` for watts at HR.
  `conditions`: `min_if`, `max_if`, `sports`, `start_hour_from`, `start_hour_to`.
  A claim without a binding feeds no prediction. Rules in `src/domestique/loop/`.

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

## Planned sessions and intent

Change `planned-sessions-and-intent`, migration `0004_planned_and_intent.sql`.

- `planned_sessions` gains `start_local timestamp` (midnight when the event is untimed),
  `sport text`, `planned_moving_s integer`, `raw jsonb` (the intervals.icu event as
  returned) and `paired_activity_id bigint → activities(id)`. A partial unique index
  keeps one activity from serving two plans. `external_id` is the event id;
  `planned_if` is the event's `icu_intensity / 100`; `structure` is its `workout_doc`.
- Ingestion (`src/domestique/ingest/icu_plan.py`) reads `GET /api/v1/athlete/{id}/events`,
  keeps `category == "WORKOUT"`, upserts on `(athlete_id, source, external_id)` and
  recomputes the pairing for the ingested range on every run.
- Pairing (`src/domestique/ingest/pairing.py`): same local date and sport family
  (`VirtualRide` pairs with `Ride`), closest start time first, at most one activity per
  plan and one plan per activity. Unpaired plans keep `paired_activity_id = NULL` and are
  reported as missed, never deleted.
- Plan vs execution (`src/domestique/analysis/plan_vs_execution.py`): one row per planned
  session with title, description, heart-rate guidance parsed from the description and
  the paired activity's NP, average and max HR, IF and work-interval HR (`activity_intervals`
  with `kind = 'WORK'`, duration-weighted, as % of `hr_max`). When the work-interval HR
  exceeds the guidance's upper bound by more than a margin (default 10 percentage points)
  a `questions` row for the athlete is written with both numbers in `context`.
- Intent (`src/domestique/intent/`): pydantic schemas for `goals.yaml`, `constraints.yaml`,
  `overrides.yaml`, `rails.yaml`; unknown fields rejected; errors name file, entry and field.
  The only write is `append_override`, which appends text to `overrides.yaml`.
- Rails (`src/domestique/rails/`): `joint-pain`, `hrv-floor`, `ramp-ceiling`, `illness`,
  each `(day: DayData, baselines, limits) -> RailResult | None`. `rails.yaml` supplies
  optional `threshold` values only; logic and wording are code.
