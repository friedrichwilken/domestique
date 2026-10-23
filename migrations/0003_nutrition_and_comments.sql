-- 0003: per-ride nutrition and activity comments (change comments-and-nutrition).
-- Absent upstream values stay NULL, never zero.

-- Platform nutrition per activity, as intervals.icu reports it.
ALTER TABLE activities
    ADD COLUMN kcal             numeric,   -- energy expended (calories)
    ADD COLUMN carbs_used_g     numeric,   -- carbohydrate used (carbs_used)
    ADD COLUMN carbs_ingested_g numeric;   -- carbohydrate ingested (carbs_ingested)

-- Platform nutrition and hydration per day.
ALTER TABLE wellness
    ADD COLUMN kcal_consumed numeric,      -- kcalConsumed
    ADD COLUMN carbs_g       numeric,      -- carbohydrates
    ADD COLUMN protein_g     numeric,      -- protein
    ADD COLUMN fat_g         numeric,      -- fatTotal
    ADD COLUMN hydration_ml  numeric,      -- hydrationVolume
    ADD COLUMN hydration     numeric;      -- hydration rating

-- Activity comments land in subjective, one row per upstream comment.
ALTER TABLE subjective
    ADD COLUMN source       text,
    ADD COLUMN external_id  text,          -- upstream comment id
    ADD COLUMN author_id    text,
    ADD COLUMN author_name  text,
    ADD COLUMN start_index  integer,       -- ride stretch the comment is pinned to
    ADD COLUMN end_index    integer,
    ADD COLUMN deleted      boolean NOT NULL DEFAULT false,
    ADD COLUMN is_system    boolean NOT NULL DEFAULT false;
-- Rows without an upstream id (NULL external_id) never collide.
ALTER TABLE subjective
    ADD CONSTRAINT subjective_upstream_key UNIQUE (athlete_id, source, external_id);
CREATE INDEX subjective_activity ON subjective (activity_id);

-- Intake per ride from the athlete's #fuel tag. The platform's carbohydrate
-- value at reconcile time is kept for audit when the tag overrides it.
CREATE TABLE activity_intake (
    activity_id         bigint PRIMARY KEY REFERENCES activities (id) ON DELETE CASCADE,
    fluid_ml            numeric,
    carbs_g             numeric,
    kcal                numeric,
    platform_carbs_g    numeric,
    carbs_differ        boolean NOT NULL DEFAULT false,
    comment_external_id text NOT NULL,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- Effective intake per ride: the tag wins, the platform fills what the tag lacks.
CREATE VIEW activity_nutrition AS
SELECT
    a.id                                        AS activity_id,
    a.athlete_id,
    a.kcal                                      AS kcal_expended,
    a.carbs_used_g,
    COALESCE(i.carbs_g, a.carbs_ingested_g)     AS carbs_ingested_g,
    CASE WHEN i.carbs_g IS NOT NULL THEN 'tag'
         WHEN a.carbs_ingested_g IS NOT NULL THEN 'platform'
    END                                         AS carbs_source,
    a.carbs_ingested_g                          AS platform_carbs_g,
    i.fluid_ml,
    i.kcal                                      AS kcal_ingested
FROM activities a
LEFT JOIN activity_intake i ON i.activity_id = a.id;
