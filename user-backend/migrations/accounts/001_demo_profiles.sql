-- Demo accounts (Accounts database). `team` is a match-relative allegiance, resolved per match.
CREATE TABLE IF NOT EXISTS demo_profiles (
    id text PRIMARY KEY,
    display_name text NOT NULL,
    team text NOT NULL CHECK (team IN ('home', 'away', 'neutral')),
    fan_style text NOT NULL CHECK (fan_style IN ('simple', 'casual', 'experienced', 'analytical'))
);
INSERT INTO demo_profiles VALUES
  ('riverton-analytical', 'Riverton Rovers analyst', 'home', 'analytical'),
  ('united-casual', 'United fan', 'away', 'casual'),
  ('neutral-simple', 'New viewer', 'neutral', 'simple')
ON CONFLICT DO NOTHING;
