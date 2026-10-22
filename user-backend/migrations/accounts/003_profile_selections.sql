-- Profiles store a selection map (layer id -> option id) of the default audience template instead of
-- fixed `team`/`fan_style` columns, so renamed or added layers need no schema change. The API validates
-- it against the default template (services/profiles.py).
ALTER TABLE demo_profiles ADD COLUMN IF NOT EXISTS selections jsonb NOT NULL DEFAULT '{}'::jsonb;
UPDATE demo_profiles SET selections = jsonb_build_object('team', team, 'fan_style', fan_style);
ALTER TABLE demo_profiles DROP COLUMN team, DROP COLUMN fan_style;
