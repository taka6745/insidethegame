-- Fictional league (PLAN.md §12 M6): fixture keys no longer name real clubs. Seeds recorded under the old keys
-- belong to recordings that no longer ship, so their start points are cleared and recorded again.
ALTER TABLE demo_settings DROP CONSTRAINT IF EXISTS demo_main_fixture_listed;
UPDATE demo_settings SET
    fixtures = array_replace(array_replace(array_replace(fixtures,
        'chelsea-united', 'riverton-forgeham'), 'arsenal-liverpool', 'redcastle-portalbion'),
        'mancity-tottenham', 'skybridge-whitmore'),
    main_fixture = CASE main_fixture WHEN 'chelsea-united' THEN 'riverton-forgeham'
                                     WHEN 'arsenal-liverpool' THEN 'redcastle-portalbion'
                                     WHEN 'mancity-tottenham' THEN 'skybridge-whitmore' ELSE main_fixture END;
UPDATE demo_settings SET start_points = (SELECT jsonb_agg(point || '{"seed": null}') FROM jsonb_array_elements(start_points) point),
    revision = revision + 1;
ALTER TABLE demo_settings ADD CONSTRAINT demo_main_fixture_listed CHECK (main_fixture = ANY(fixtures));
