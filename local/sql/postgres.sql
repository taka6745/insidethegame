-- Development scaffolding. Production schema/migrations belong to user-backend/.
CREATE DATABASE matchapp;
CREATE TABLE demo_profiles (
    id text PRIMARY KEY,
    display_name text NOT NULL,
    team text NOT NULL CHECK (team IN ('home', 'away', 'neutral')),
    fan_style text NOT NULL CHECK (fan_style IN ('simple', 'casual', 'experienced', 'analytical'))
);
INSERT INTO demo_profiles VALUES
  ('chelsea-analytical', 'Chelsea analyst', 'home', 'analytical'),
  ('united-casual', 'United fan', 'away', 'casual'),
  ('neutral-simple', 'New viewer', 'neutral', 'simple');
