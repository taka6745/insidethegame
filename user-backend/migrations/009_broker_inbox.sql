CREATE TABLE IF NOT EXISTS broker_narrative_inbox (
    snapshot_id text PRIMARY KEY,
    run_id text NOT NULL,
    audience_revision bigint NOT NULL,
    document jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS broker_narrative_run ON broker_narrative_inbox(run_id);
