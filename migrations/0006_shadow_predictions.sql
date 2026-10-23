-- 0006: loop calibration (change loop-calibration). Earlier files stay as they were.

-- Shadow scoring: every applicable claim gets its own prediction per session and
-- metric. The one the precedence rule picks is the official prediction (the one
-- reported); the others are shadows, scored the same way so a rival can take over
-- without waiting for the winner to fail. Before this change the predictor cited
-- exactly one claim per prediction, so existing rows key on claim_ids[1] and are
-- all official.
ALTER TABLE predictions
    ADD COLUMN claim_id uuid REFERENCES claims (id),
    ADD COLUMN official boolean NOT NULL DEFAULT true;
UPDATE predictions SET claim_id = claim_ids[1];
-- Fails (and rolls back) if an old row cites no claim, rather than invent one.
ALTER TABLE predictions ALTER COLUMN claim_id SET NOT NULL;
-- New rows must say whether they are official.
ALTER TABLE predictions ALTER COLUMN official DROP DEFAULT;

DROP INDEX predictions_session_metric;
-- Pre-registered once per session, metric and claim.
CREATE UNIQUE INDEX predictions_session_metric_claim
    ON predictions (planned_session_id, metric, claim_id);
-- At most one official prediction per session and metric.
CREATE UNIQUE INDEX predictions_session_metric_official
    ON predictions (planned_session_id, metric) WHERE official;

-- Range calibration replaces the always-hit flag (hit rate above 95%), which fired
-- on well-sized ranges. Its flags came from that discredited rule and are dropped,
-- not carried over. The window counts outcomes since the last time a human cleared
-- the flags; the sums are in the unit of the claim's metric.
ALTER TABLE claims
    DROP COLUMN always_hit,
    -- mean absolute error under a third of the mean half-range, over >= 10 outcomes
    ADD COLUMN uninformative    boolean NOT NULL DEFAULT false,
    -- hit rate under 60%, over >= 10 outcomes
    ADD COLUMN overconfident    boolean NOT NULL DEFAULT false,
    ADD COLUMN calib_scored     integer NOT NULL DEFAULT 0 CHECK (calib_scored >= 0),
    ADD COLUMN calib_hits       integer NOT NULL DEFAULT 0,
    ADD COLUMN calib_abs_error  numeric NOT NULL DEFAULT 0 CHECK (calib_abs_error >= 0),
    ADD COLUMN calib_half_range numeric NOT NULL DEFAULT 0 CHECK (calib_half_range >= 0),
    ADD CONSTRAINT claims_calib_hits_check
        CHECK (calib_hits >= 0 AND calib_hits <= calib_scored);
