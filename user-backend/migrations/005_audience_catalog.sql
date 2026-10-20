-- Configuration ownership is separate from narrative authoring/storage.
-- Do not reuse the retired experimental audience_config/narrative cache tables.
CREATE TABLE IF NOT EXISTS audience_catalog (
    match_id text PRIMARY KEY,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    document jsonb NOT NULL
);
