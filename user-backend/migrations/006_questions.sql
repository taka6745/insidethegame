CREATE TABLE IF NOT EXISTS question_conversations (
    id uuid PRIMARY KEY,
    profile_id text NOT NULL,
    run_id text NOT NULL,
    match_id text NOT NULL,
    UNIQUE (profile_id, run_id)
);
CREATE TABLE IF NOT EXISTS question_sessions (
    profile_id text PRIMARY KEY,
    token uuid UNIQUE NOT NULL,
    conversation_id uuid NOT NULL REFERENCES question_conversations(id)
);
CREATE TABLE IF NOT EXISTS question_turns (
    id bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES question_conversations(id),
    request_id uuid NOT NULL,
    prompt text NOT NULL,
    status text NOT NULL,
    reply jsonb,
    UNIQUE (conversation_id, request_id)
);
CREATE TABLE IF NOT EXISTS question_offers (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES question_conversations(id),
    turn_id bigint NOT NULL REFERENCES question_turns(id),
    document jsonb NOT NULL,
    calculation_id text
);
