-- Tunables owned by this service, served and edited under /dev/config/{table} (ETag + expected_revision).
-- Purges never touch these rows. Documents are validated by backend/models/config.py.
CREATE TABLE IF NOT EXISTS backend_config (
    name text PRIMARY KEY,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    document jsonb NOT NULL
);
-- Stat ids are the frozen ETL catalogue ids; {team} is the viewer's supported contestant id.
INSERT INTO backend_config (name, document) VALUES ('presentation', '{
  "card_slots": 5,
  "default_stats": {
    "team": ["{team}:goals", "{team}:shots", "{team}:corners", "{team}:passes", "{team}:cards"],
    "neutral": ["all:goals", "all:shots", "all:corners", "all:passes", "all:cards"]},
  "fallback_stats": {
    "team": ["{team}:goals", "{team}:shots", "{team}:passes", "{team}:possession", "{team}:pass_accuracy"],
    "neutral": ["all:goals", "all:shots", "all:passes", "all:possession", "all:pass_accuracy"]},
  "excluded_stats": ["all:possession"],
  "protected_stat_kinds": ["goals"]
}'::jsonb) ON CONFLICT DO NOTHING;
-- Seconds before/after an event's video time; lead-in multipliers; clip and page limits.
INSERT INTO backend_config (name, document) VALUES ('replay-timing', '{
  "timing": {"goal": [10.0, 2.0], "shot": [6.0, 3.0], "penalty": [6.0, 4.0], "save": [6.0, 3.0],
             "card": [5.0, 4.0], "foul": [5.0, 4.0], "foul_won": [5.0, 4.0], "offside": [5.0, 3.0],
             "corner": [3.0, 6.0], "free_kick": [3.0, 6.0], "corner_awarded": [4.0, 3.0]},
  "default": [4.0, 2.0],
  "lead_in": {"short": 0.5, "normal": 1.0, "long": 2.0},
  "max_clips": 12, "max_seconds": 180.0, "max_move_seconds": 25.0, "merge_gap": 1.0, "max_items": 36
}'::jsonb) ON CONFLICT DO NOTHING;
-- Key-moment rank per kind (1 = most important); `dismissal` is a red or second-yellow card.
INSERT INTO backend_config (name, document) VALUES ('key-moment-ranks', '{
  "ranks": {"goal": 1, "dismissal": 2, "penalty": 3, "card": 4}
}'::jsonb) ON CONFLICT DO NOTHING;
