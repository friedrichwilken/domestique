-- 0004: planned sessions carry what pairing and the plan-vs-execution join need.
-- Change `planned-sessions-and-intent`. Additive only; 0001 stays as it was.

ALTER TABLE planned_sessions
    ADD COLUMN start_local        timestamp,   -- athlete's local wall clock, midnight when untimed
    ADD COLUMN sport              text,        -- platform type as given (Ride, Run, ...)
    ADD COLUMN planned_moving_s   integer,
    ADD COLUMN raw                jsonb,       -- the event exactly as the platform returned it
    -- at most one executed activity per planned session, recorded by the pairing step
    ADD COLUMN paired_activity_id bigint REFERENCES activities (id) ON DELETE SET NULL;

CREATE INDEX planned_sessions_athlete_date ON planned_sessions (athlete_id, date);

-- An activity pairs to at most one planned session.
CREATE UNIQUE INDEX planned_sessions_paired_activity
    ON planned_sessions (paired_activity_id) WHERE paired_activity_id IS NOT NULL;
