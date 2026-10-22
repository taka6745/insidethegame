"""Clip lengths (PLAN.md §12 M7): clips of different moments ran very unevenly, a quick shot with a short lead-in
lasting a few seconds while a goal's move ran past twenty. `replay-timing.min_clip_seconds` (8 s) widens any shorter
cut, and a goal keeps 5 s after the ball goes in (was 2 s, cutting the reaction). A key is changed only where it still
holds its 016 seed value; /dev/ edits are kept. A changed row gets a new revision."""
from psycopg.types.json import Jsonb

GOAL_BEFORE_AND_OLD_AFTER, GOAL_AFTER = [10.0, 2.0], 5.0
MIN_CLIP_SECONDS = 8.0


def tuned(document):
    changed = dict(document)
    if 'min_clip_seconds' not in document:
        changed['min_clip_seconds'] = MIN_CLIP_SECONDS
    if list(document.get('timing', {}).get('goal') or []) == GOAL_BEFORE_AND_OLD_AFTER:
        changed['timing'] = {**document['timing'], 'goal': [GOAL_BEFORE_AND_OLD_AFTER[0], GOAL_AFTER]}
    return changed


def migrate(conn):
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'replay-timing'").fetchone()
    if row is None:
        return
    document = row['document']
    changed = tuned(document)
    if changed != document:
        conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'replay-timing'",
                     (Jsonb(changed),))
