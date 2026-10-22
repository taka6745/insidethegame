-- Answer prices for viewer receipts (US dollars per million tokens): configuration, never a provider's price list.
INSERT INTO backend_config (name, document) VALUES ('prices', '{"input": 0.4, "output": 1.6}'::jsonb)
ON CONFLICT DO NOTHING;
-- Seconds a missing seq may block a match before it is recovered from ETL or skipped.
INSERT INTO backend_config (name, document) VALUES ('stream', '{"gap_timeout_seconds": 30}'::jsonb)
ON CONFLICT DO NOTHING;

-- Missing seqs this service filled: `recovered` from ETL's canonical event, or `skipped`
-- (a deleted placeholder event keeps seq contiguous).
CREATE TABLE IF NOT EXISTS match_gaps (
    match_id text NOT NULL REFERENCES received_matches(match_id) ON DELETE CASCADE,
    seq integer NOT NULL CHECK (seq > 0),
    state text NOT NULL CHECK (state IN ('recovered', 'skipped')),
    blocked_seconds real NOT NULL,
    resolved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, seq)
);
