-- The start point a run began from (a seeded demo start); the viewer says "live from" it.
ALTER TABLE runs ADD COLUMN start_point text;
