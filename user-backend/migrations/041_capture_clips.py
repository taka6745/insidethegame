"""Capture clips (PLAN.md §10.2 D6–D7).

- `narrative_clips`: a key event's clip on the shared bucket narratives (the engine's `MomentClip` message), one
  row per (bucket, key moment); match-scoped, purged and seeded with the match.
- `subscriptions.clips.always_for` (topic kinds clip-on from creation) and `.shared` (D7 on), from 024's seed where
  missing; a /dev/ edit of either is kept. A changed row gets a new revision.
"""
import importlib.util
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent

DDL = '''
CREATE TABLE IF NOT EXISTS narrative_clips (
    match_id text NOT NULL,
    bucket_id text NOT NULL,
    moment_id text NOT NULL,
    event_seq integer NOT NULL CHECK (event_seq >= 0),
    step_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, bucket_id, moment_id)
);
'''


def migrate(conn):
    spec = importlib.util.spec_from_file_location('m024', HERE / '024_subscriptions.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    conn.execute(DDL)
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'").fetchone()
    if row is None or 'clips' not in row['document']:
        return
    clips, added = dict(row['document']['clips']), False
    for key in ('always_for', 'shared'):
        if key not in clips:
            clips[key], added = seed.CONFIG['subscriptions']['clips'][key], True
    if added:
        conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'subscriptions'",
                     (Jsonb({**row['document'], 'clips': clips}),))
