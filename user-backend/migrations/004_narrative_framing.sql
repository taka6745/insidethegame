CREATE TABLE IF NOT EXISTS audience_config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    document jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS neutral_narratives (
    match_id text NOT NULL,
    narrative_id text NOT NULL,
    revision integer NOT NULL,
    document jsonb NOT NULL,
    PRIMARY KEY (match_id, narrative_id, revision)
);
CREATE TABLE IF NOT EXISTS narrative_variants (
    match_id text NOT NULL,
    narrative_id text NOT NULL,
    revision integer NOT NULL,
    bucket_id text NOT NULL,
    framing_key text NOT NULL,
    text text NOT NULL,
    mode text NOT NULL,
    PRIMARY KEY (match_id, narrative_id, revision, bucket_id, framing_key),
    FOREIGN KEY (match_id, narrative_id, revision)
        REFERENCES neutral_narratives(match_id, narrative_id, revision)
);
CREATE TABLE IF NOT EXISTS narrative_framing_leases (
    match_id text NOT NULL,
    narrative_id text NOT NULL,
    owner uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (match_id, narrative_id)
);
