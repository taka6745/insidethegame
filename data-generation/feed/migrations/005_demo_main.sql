-- The demo's main game: it starts first (so it is always furthest along) and the viewer opens it by default.
-- The other fixtures stay reachable from the picker.
ALTER TABLE demo_settings ADD COLUMN main_fixture text;
UPDATE demo_settings SET main_fixture = CASE WHEN 'arsenal-liverpool' = ANY(fixtures) THEN 'arsenal-liverpool'
                                             ELSE fixtures[1] END;
UPDATE demo_settings SET fixtures = ARRAY[main_fixture] || array_remove(fixtures, main_fixture);
ALTER TABLE demo_settings ALTER COLUMN main_fixture SET NOT NULL,
    ADD CONSTRAINT demo_main_fixture_listed CHECK (main_fixture = ANY(fixtures));
