-- 0001 data plane (docs/schema.md). Postgres 16 + TimescaleDB.
-- Timestamps are UTC (timestamptz); the athlete's local wall-clock start is
-- stored alongside as start_local (timestamp without zone).

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE activities (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    athlete_id    text        NOT NULL,
    source        text        NOT NULL,
    external_id   text        NOT NULL,
    start_local   timestamp   NOT NULL,
    start_utc     timestamptz,
    sport         text,
    name          text,
    moving_s      integer,
    avg_w         numeric,
    np_w          numeric,
    avg_hr        numeric,
    max_hr        numeric,
    avg_cad       numeric,
    ftp_at_ride   numeric,
    load          numeric,
    "if"          numeric,          -- intensity factor
    ef            numeric,          -- efficiency factor (NP / avg HR)
    decoupling    numeric,          -- percent
    lr_balance    numeric,          -- left-leg share, percent
    raw           jsonb,
    UNIQUE (athlete_id, source, external_id)
);
CREATE INDEX activities_athlete_start ON activities (athlete_id, start_local);

CREATE TABLE activity_streams (
    activity_id bigint  NOT NULL REFERENCES activities (id) ON DELETE CASCADE,
    t_s         integer NOT NULL,
    watts       numeric,
    hr          numeric,
    cadence     numeric,
    lr          numeric,
    temp        numeric,
    PRIMARY KEY (activity_id, t_s)
);
-- Partitioned by activity: one activity's stream stays in one chunk.
SELECT create_hypertable(
    'activity_streams', by_range('activity_id', 1000), if_not_exists => TRUE
);

CREATE TABLE activity_intervals (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activity_id bigint  NOT NULL REFERENCES activities (id) ON DELETE CASCADE,
    idx         integer NOT NULL,
    kind        text,
    start_s     integer,
    dur_s       integer,
    avg_w       numeric,
    avg_hr      numeric,
    max_hr      numeric,
    avg_cad     numeric,
    lr_balance  numeric,
    UNIQUE (activity_id, idx)
);

CREATE TABLE planned_sessions (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    athlete_id   text NOT NULL,
    source       text NOT NULL,
    external_id  text NOT NULL,
    date         date NOT NULL,
    title        text,
    description  text,
    structure    jsonb,
    planned_tss  numeric,
    planned_if   numeric,
    intent_ref   text,
    UNIQUE (athlete_id, source, external_id)
);

CREATE TABLE wellness (
    athlete_id   text NOT NULL,
    date         date NOT NULL,
    hrv          numeric,
    rhr          numeric,
    sleep_s      integer,
    sleep_score  numeric,
    weight       numeric,
    ctl          numeric,
    atl          numeric,
    source       text NOT NULL,
    raw          jsonb,
    PRIMARY KEY (athlete_id, date)
);

CREATE TABLE ftp_history (
    athlete_id  text    NOT NULL,
    valid_from  date    NOT NULL,
    ftp_w       numeric NOT NULL,
    source      text    NOT NULL,
    PRIMARY KEY (athlete_id, valid_from)
);

CREATE TABLE subjective (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    athlete_id   text        NOT NULL,
    ts           timestamptz NOT NULL,
    activity_id  bigint REFERENCES activities (id) ON DELETE SET NULL,
    rpe          numeric,
    feel         text,
    answer       text,
    tags         text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX subjective_athlete_ts ON subjective (athlete_id, ts);

CREATE TABLE context (
    athlete_id  text NOT NULL,
    date        date NOT NULL,
    kind        text NOT NULL,   -- work day, med day, travel, race, illness
    value       text,
    PRIMARY KEY (athlete_id, date, kind)
);

CREATE TABLE tests (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    athlete_id   text  NOT NULL,
    date         date  NOT NULL,
    kind         text  NOT NULL,   -- ground truth: threshold, step, ...
    result       jsonb NOT NULL,
    activity_id  bigint REFERENCES activities (id) ON DELETE SET NULL
);
