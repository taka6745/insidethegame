CREATE TABLE IF NOT EXISTS viewers (
    match_id text NOT NULL,
    profile_id text NOT NULL,
    token uuid NOT NULL UNIQUE,
    state jsonb NOT NULL,
    PRIMARY KEY (match_id, profile_id)
);
