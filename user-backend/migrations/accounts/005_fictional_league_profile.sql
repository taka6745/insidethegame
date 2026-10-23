-- Fictional league: the home analyst's profile id no longer names a real club.
-- Match-app rows keyed by profile id are per-run and purged with each match, so only the profile moves.
UPDATE demo_profiles SET id = 'riverton-analytical' WHERE id = 'chelsea-analytical'
  AND NOT EXISTS (SELECT 1 FROM demo_profiles WHERE id = 'riverton-analytical');
