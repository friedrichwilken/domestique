-- 0005: prediction loop (change claims-and-prediction-loop, tasks 3.1-3.3).
-- Additive except for one column retype on predictions; earlier files stay as they were.

-- 0002 declared predictions.planned_session_id as uuid before planned_sessions
-- existed; planned_sessions.id is bigint. Nothing wrote predictions before this
-- change. Re-adding the column NOT NULL fails on a non-empty table, so this
-- migration refuses (and rolls back) rather than drop data silently.
ALTER TABLE predictions DROP COLUMN planned_session_id;
ALTER TABLE predictions
    ADD COLUMN planned_session_id bigint NOT NULL REFERENCES planned_sessions (id),
    -- what the prediction was computed from (HR band, base value, rides, superseded
    -- claims), written with it so scoring uses the pre-registered inputs
    ADD COLUMN basis jsonb NOT NULL DEFAULT '{}',
    ADD CONSTRAINT predictions_metric_check
        CHECK (metric IN ('watts_at_hr', 'peak_hr', 'hrv_next_morning', 'sleep_hours')),
    ADD CONSTRAINT predictions_range_check
        CHECK (low IS NOT NULL AND high IS NOT NULL AND low <= expected AND expected <= high);

-- Pre-registered once: one prediction per session and metric.
CREATE UNIQUE INDEX predictions_session_metric ON predictions (planned_session_id, metric);

-- How a claim feeds a metric. Claims are prose; a binding is the machine-readable
-- rule the predictor applies. A claim without a binding feeds no prediction.
--   expected = base * (1 + change_pct / 100) + offset
--   range    = expected -/+ (expected * range_pct / 100 + range_abs)
-- conditions: optional min_if, max_if, sports, start_hour_from, start_hour_to.
CREATE TABLE claim_bindings (
    claim_id   uuid NOT NULL REFERENCES claims (id),
    metric     text NOT NULL
        CHECK (metric IN ('watts_at_hr', 'peak_hr', 'hrv_next_morning', 'sleep_hours')),
    params     jsonb NOT NULL DEFAULT '{}',
    conditions jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (claim_id, metric)
);
