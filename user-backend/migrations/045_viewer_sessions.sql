-- Each browser is its own viewer: two people on the same demo profile no longer share one conversation
-- or take over each other's session. Existing rows keep viewer_id '' (lab and pre-045 clients).
ALTER TABLE question_conversations ADD COLUMN viewer_id text NOT NULL DEFAULT '';
ALTER TABLE question_conversations DROP CONSTRAINT question_conversations_profile_id_match_id_key;
ALTER TABLE question_conversations ADD CONSTRAINT question_conversations_viewer_key UNIQUE (viewer_id, profile_id, match_id);
ALTER TABLE question_sessions ADD COLUMN viewer_id text NOT NULL DEFAULT '';
ALTER TABLE question_sessions DROP CONSTRAINT question_sessions_pkey;
ALTER TABLE question_sessions ADD PRIMARY KEY (viewer_id, profile_id, match_id);
