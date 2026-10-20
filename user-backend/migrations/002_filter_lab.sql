CREATE TABLE IF NOT EXISTS filter_lab_run (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    run_id uuid NOT NULL UNIQUE,
    source_hash text NOT NULL,
    position integer NOT NULL DEFAULT 0 CHECK (position >= 0),
    status text NOT NULL DEFAULT 'ready'
);
CREATE TABLE IF NOT EXISTS filter_lab_calculations (
    run_id uuid NOT NULL REFERENCES filter_lab_run(run_id) ON DELETE CASCADE,
    calculation_id text NOT NULL,
    label text NOT NULL,
    rule jsonb NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (run_id, calculation_id)
);
