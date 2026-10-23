"""Cross-match reach and follow offers.

- `backend_config` rows `cross-match` (questions, pins and follows about the other live matches) and
  `follow-offer` (the "Follow this story?" offer on answers); an existing row, a /dev/ edit, is kept.
- `subscriptions.bucket_id`: the bucket a follow of another match is written for (that match's own catalogue; the
  viewer's bucket names positions in their own match). Null: the follower's own bucket, as before.
"""
from psycopg.types.json import Jsonb

CONFIG = {'enabled': True, 'min_name_coverage': 0.5, 'suggest_teams': True}
OFFER = {'enabled': True,
         'instructions': 'Does this question ask about something that develops over the match rather than a single fact?',
         'true': 'It asks about something that keeps developing as the match goes on.',
         'false': 'It asks for one fact, figure or moment.',
         'min_probability': 0.6, 'max_per_minute': 3, 'timeout_seconds': 6}


def migrate(conn):
    conn.execute("INSERT INTO backend_config (name, document) VALUES ('cross-match', %s) ON CONFLICT DO NOTHING",
                 (Jsonb(CONFIG),))
    conn.execute("INSERT INTO backend_config (name, document) VALUES ('follow-offer', %s) ON CONFLICT DO NOTHING",
                 (Jsonb(OFFER),))
    conn.execute('ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS bucket_id text')
