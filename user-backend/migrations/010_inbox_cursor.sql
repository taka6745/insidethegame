ALTER TABLE broker_narrative_inbox ADD COLUMN IF NOT EXISTS snapshot_cursor integer;
CREATE INDEX IF NOT EXISTS broker_narrative_run_cursor ON broker_narrative_inbox(run_id, snapshot_cursor);
