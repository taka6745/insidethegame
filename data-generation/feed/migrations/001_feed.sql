-- Feed provider: recordings catalogue, runs and permanent purge tombstones.
CREATE TABLE recordings (
    fixture text PRIMARY KEY,
    source_match_id text NOT NULL,
    description text NOT NULL,
    teams jsonb NOT NULL,
    duration_seconds double precision NOT NULL,
    capabilities jsonb NOT NULL,
    synthetic boolean NOT NULL,
    sha256 text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
    run_id uuid PRIMARY KEY,
    match_id text NOT NULL UNIQUE,
    fixture text NOT NULL,
    kickoff timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL CHECK (status IN ('scheduled', 'live', 'finished')),
    position integer NOT NULL DEFAULT 0,  -- items sent: 1 = MA1, then the stream in send order
    seq integer NOT NULL DEFAULT 0         -- latest canonical MatchEvent seq sent
);

-- matchIds are never reused, so tombstones are permanent.
CREATE TABLE purged_matches (
    match_id text PRIMARY KEY,
    purged_at timestamptz NOT NULL DEFAULT now()
);

-- Latest `all` purge; runs created before it never resume.
CREATE TABLE purge_cutoff (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    cutoff timestamptz NOT NULL
);
