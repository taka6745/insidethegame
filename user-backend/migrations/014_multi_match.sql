-- Multi-match: one row set per feed matchId ({fixture}-{run8}), learned from the stream.
-- The single-run lab, legacy viewer harness and stand-in inbox are retired with their rows.
DROP TABLE IF EXISTS viewers, filter_lab_calculations, filter_lab_run, broker_narrative_inbox CASCADE;
DROP TABLE IF EXISTS question_offers, question_turns, question_sessions, question_conversations CASCADE;
DROP TABLE IF EXISTS engine_narratives;

-- Purge tombstones are permanent: a matchId is never reused or revived.
CREATE TABLE match_tombstones (
    match_id text PRIMARY KEY,
    purged_at timestamptz NOT NULL DEFAULT now()
);
-- `purge all` cut-off: an MA1 sent before it is dropped.
CREATE TABLE match_purge_cutoff (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    cutoff timestamptz NOT NULL
);
-- Matches whose MA1 this service stored; other match messages are dropped.
CREATE TABLE received_matches (
    match_id text PRIMARY KEY CHECK (length(match_id) BETWEEN 1 AND 64),
    fixture text NOT NULL,
    source_match_id text,
    run_id text,
    provenance text,
    sent_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);
-- Every received canonical MatchEvent v2, the only input to custom rules.
CREATE TABLE received_events (
    match_id text NOT NULL REFERENCES received_matches(match_id) ON DELETE CASCADE,
    seq integer NOT NULL CHECK (seq > 0),
    event jsonb NOT NULL,
    PRIMARY KEY (match_id, seq)
);
CREATE TABLE match_calculations (
    match_id text NOT NULL REFERENCES received_matches(match_id) ON DELETE CASCADE,
    calculation_id text NOT NULL,
    label text NOT NULL,
    rule jsonb NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (match_id, calculation_id)
);
-- Event Hubs position per partition, committed with the event it follows.
CREATE TABLE stream_checkpoints (
    partition_id text PRIMARY KEY,
    sequence_number bigint NOT NULL
);

-- Chat sessions per (profile, match): one profile may watch several matches at once.
CREATE TABLE question_conversations (
    id uuid PRIMARY KEY,
    profile_id text NOT NULL,
    match_id text NOT NULL REFERENCES received_matches(match_id) ON DELETE CASCADE,
    audience jsonb,
    UNIQUE (profile_id, match_id)
);
CREATE TABLE question_sessions (
    profile_id text NOT NULL,
    match_id text NOT NULL,
    token uuid UNIQUE NOT NULL,
    conversation_id uuid NOT NULL REFERENCES question_conversations(id) ON DELETE CASCADE,
    PRIMARY KEY (profile_id, match_id)
);
CREATE TABLE question_turns (
    id bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES question_conversations(id) ON DELETE CASCADE,
    request_id uuid NOT NULL,
    prompt text NOT NULL,
    status text NOT NULL,
    reply jsonb,
    UNIQUE (conversation_id, request_id)
);
CREATE TABLE question_offers (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES question_conversations(id) ON DELETE CASCADE,
    turn_id bigint NOT NULL REFERENCES question_turns(id) ON DELETE CASCADE,
    document jsonb NOT NULL,
    calculation_id text
);

-- Live narratives from the narrative engine (its `narratives` topic contract), per match.
CREATE TABLE engine_narratives (
    id text PRIMARY KEY,
    match_id text NOT NULL REFERENCES received_matches(match_id) ON DELETE CASCADE,
    bucket_id text NOT NULL,
    seq integer NOT NULL,
    step_id text NOT NULL,
    period integer NOT NULL,
    time_min integer NOT NULL,
    time_sec integer NOT NULL,
    clock_seconds integer NOT NULL,
    event_seq integer,
    text text NOT NULL,
    trigger jsonb NOT NULL,
    prompt_version text,
    tokens jsonb,
    audience_revision integer,
    created_at text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX engine_narratives_match_clock ON engine_narratives(match_id, period, clock_seconds);
