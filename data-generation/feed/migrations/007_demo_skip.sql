-- Demo fast-forward (PLAN.md §12 M13, DEMO_SEEDS only): where "Skip ahead" can jump a live demo. Each target
-- is either a number of match minutes or a start point (read on the main game's clock). Set with PUT /demo.
ALTER TABLE demo_settings ADD COLUMN skip_targets jsonb NOT NULL DEFAULT
    '[{"id": "10", "label": "+10′", "minutes": 10},
      {"id": "20", "label": "+20′", "minutes": 20},
      {"id": "ht", "label": "Second half", "point": "ht"}]';
