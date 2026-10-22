-- Key-event clips go with their match: a clip saved while its match was being purged cannot outlive it
-- (041 had no parent key, so purge-all, which walks received_matches, never reached such a row).
DELETE FROM narrative_clips c WHERE NOT EXISTS (SELECT 1 FROM received_matches m WHERE m.match_id = c.match_id);
ALTER TABLE narrative_clips ADD CONSTRAINT narrative_clips_match_fk
    FOREIGN KEY (match_id) REFERENCES received_matches(match_id) ON DELETE CASCADE;
