-- Profiles serve every fixture: name the seeded ones by side, not club. Edited names are kept.
UPDATE demo_profiles SET display_name = 'Home analyst' WHERE id = 'riverton-analytical' AND display_name = 'Riverton Rovers analyst';
UPDATE demo_profiles SET display_name = 'Away fan' WHERE id = 'united-casual' AND display_name = 'United fan';
