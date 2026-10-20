-- Imported development recordings survive a process restart. The default stays in Git.
ALTER TABLE filter_lab_run ADD COLUMN IF NOT EXISTS recording_text text;
ALTER TABLE filter_lab_run ADD COLUMN IF NOT EXISTS recording_filename text;
