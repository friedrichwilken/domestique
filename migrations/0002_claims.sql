-- 0002: athlete model (claims) and prediction loop. Postgres 16.

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid() on older builds

CREATE TYPE source_layer AS ENUM ('observed', 'stated', 'prior');
CREATE TYPE claim_horizon AS ENUM ('day', 'week', 'season');
CREATE TYPE claim_status AS ENUM ('active', 'retired', 'candidate');
CREATE TYPE evidence_kind AS ENUM
    ('activity', 'interval', 'wellness', 'statement', 'reference', 'query');
CREATE TYPE question_for AS ENUM ('athlete', 'reviewer');

CREATE TABLE claims (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id     text NOT NULL,
    text           text NOT NULL,
    source_layer   source_layer NOT NULL,
    -- how long until predictions from this claim can be scored
    horizon        claim_horizon NOT NULL,
    confidence     numeric(4, 3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status         claim_status NOT NULL DEFAULT 'candidate',
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_tested_at timestamptz,
    created_by     text NOT NULL,
    -- consecutive confirmed predictions, used by the prior -> observed rule
    hit_streak     integer NOT NULL DEFAULT 0 CHECK (hit_streak >= 0),
    -- scored predictions and hits, for the always-hit flag
    scored         integer NOT NULL DEFAULT 0 CHECK (scored >= 0),
    hits           integer NOT NULL DEFAULT 0 CHECK (hits >= 0 AND hits <= scored),
    always_hit     boolean NOT NULL DEFAULT false,
    CHECK (horizon <> 'week' OR confidence <= 0.7),
    CHECK (horizon <> 'season' OR confidence <= 0.5)
);
CREATE INDEX claims_athlete_status_idx ON claims (athlete_id, status);

CREATE TABLE claim_history (
    claim_id   uuid NOT NULL REFERENCES claims (id),
    ts         timestamptz NOT NULL DEFAULT now(),
    confidence numeric(4, 3) NOT NULL,
    status     claim_status NOT NULL,
    reason     text NOT NULL,
    by         text NOT NULL
);
CREATE INDEX claim_history_claim_idx ON claim_history (claim_id, ts);

-- Append-only: no UPDATE, no DELETE.
CREATE FUNCTION claim_history_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'claim_history is append-only (% rejected)', TG_OP;
END;
$$;

CREATE TRIGGER claim_history_no_update_delete
    BEFORE UPDATE OR DELETE ON claim_history
    FOR EACH ROW EXECUTE FUNCTION claim_history_append_only();

CREATE TRIGGER claim_history_no_truncate
    BEFORE TRUNCATE ON claim_history
    FOR EACH STATEMENT EXECUTE FUNCTION claim_history_append_only();

CREATE TABLE evidence (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id uuid NOT NULL REFERENCES claims (id),
    kind     evidence_kind NOT NULL,
    ref      text NOT NULL,
    note     text
);
CREATE INDEX evidence_claim_idx ON evidence (claim_id);

-- planned_sessions arrives with the data-plane migration (task 001); no FK
-- here so this migration stands alone.
CREATE TABLE predictions (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    planned_session_id uuid NOT NULL,
    metric            text NOT NULL,
    expected          numeric NOT NULL,
    low               numeric,
    high              numeric,
    claim_ids         uuid[] NOT NULL DEFAULT '{}',
    made_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX predictions_session_idx ON predictions (planned_session_id);

CREATE TABLE outcomes (
    prediction_id uuid PRIMARY KEY REFERENCES predictions (id),
    actual        numeric NOT NULL,
    error         numeric NOT NULL,
    scored_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE questions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id  text NOT NULL,
    "for"       question_for NOT NULL,
    text        text NOT NULL,
    context     jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'open',
    created_at  timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    answer      text
);
CREATE INDEX questions_open_idx ON questions (athlete_id, status);
