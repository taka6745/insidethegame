-- Profiles serve every fixture: name the seeded ones by side, not club. Edited names are kept.
UPDATE demo_profiles SET display_name = 'Home analyst' WHERE id = 'chelsea-analytical' AND display_name = 'Chelsea analyst';
UPDATE demo_profiles SET display_name = 'Away fan' WHERE id = 'united-casual' AND display_name = 'United fan';
