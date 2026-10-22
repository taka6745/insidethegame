"""Moment clips in follows (PLAN.md §10.2 D3): a followed topic's playlist of moments Decision-1 judged worth a clip.

- `subscription_clips`: one row per (topic, key moment) Decision-1 judged worth a clip (the engine's `FollowClip`
  message; 039 renames `narrative_id` to `step_id`); match-scoped and purged with the match (its topic cascades too).
- `subscriptions.clips`, from 024's seed, where missing (the engine requires it). A changed row gets a new revision.
"""
import importlib.util
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent

DDL = '''
CREATE TABLE IF NOT EXISTS subscription_clips (
    match_id text NOT NULL,
    topic_id text NOT NULL,
    moment_id text NOT NULL,
    event_seq integer NOT NULL CHECK (event_seq >= 0),
    narrative_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, topic_id, moment_id),
    FOREIGN KEY (match_id, topic_id) REFERENCES subscription_topics (match_id, topic_id) ON DELETE CASCADE
);
'''


def migrate(conn):
    spec = importlib.util.spec_from_file_location('m024', HERE / '024_subscriptions.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    conn.execute(DDL)
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'subscriptions'").fetchone()
    if row is not None and 'clips' not in row['document']:
        conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'subscriptions'",
                     (Jsonb({**row['document'], 'clips': seed.CONFIG['subscriptions']['clips']}),))
