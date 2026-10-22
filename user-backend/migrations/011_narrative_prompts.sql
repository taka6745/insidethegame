-- Append-only prompt versions; one active pointer per role. The revision grows on every activation.
CREATE TABLE IF NOT EXISTS narrative_prompts (
    role text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    template text NOT NULL,
    placeholders text[] NOT NULL,
    source text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (role, version)
);
CREATE TABLE IF NOT EXISTS narrative_prompt_active (
    role text PRIMARY KEY,
    version integer NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    FOREIGN KEY (role, version) REFERENCES narrative_prompts(role, version)
);
