-- Demo profiles are edited under /dev/profiles with one revision for the whole set.
-- `team` and `fan_style` are default audience options, checked by the API against the default template
-- (services/profiles.py), not by fixed CHECKs.
ALTER TABLE demo_profiles DROP CONSTRAINT IF EXISTS demo_profiles_team_check,
                          DROP CONSTRAINT IF EXISTS demo_profiles_fan_style_check;
CREATE TABLE IF NOT EXISTS demo_profile_revision (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0)
);
INSERT INTO demo_profile_revision DEFAULT VALUES ON CONFLICT DO NOTHING;
