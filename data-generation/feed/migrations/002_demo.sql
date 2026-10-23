-- The demo: which fixtures one "Start demo" kicks off, how far apart, the cap on concurrent runs, and the
-- points it may start from (match clock; each fixture maps it to its own video second). A point after kick-off needs a recorded seed; `seed` names it.
CREATE TABLE demo_settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    fixtures text[] NOT NULL CHECK (cardinality(fixtures) >= 1),
    stagger_seconds integer NOT NULL CHECK (stagger_seconds BETWEEN 0 AND 3600),
    max_active_runs integer NOT NULL CHECK (max_active_runs >= cardinality(fixtures)),
    start_points jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 1
);

INSERT INTO demo_settings (fixtures, stagger_seconds, max_active_runs, start_points)
VALUES (ARRAY['riverton-forgeham', 'redcastle-portalbion', 'skybridge-whitmore'], 120, 3,
        '[{"id": "kickoff", "label": "Kick-off", "period": 1, "minute": 0, "seed": null},
          {"id": "20", "label": "20′", "period": 1, "minute": 20, "seed": null},
          {"id": "ht", "label": "Second half", "period": 2, "minute": 45, "seed": null},
          {"id": "60", "label": "60′", "period": 2, "minute": 60, "seed": null},
          {"id": "85", "label": "85′", "period": 2, "minute": 85, "seed": null}]');
