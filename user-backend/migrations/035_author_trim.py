"""An excerpt keeps its supported sentences.

One unsupported sentence dropped a whole excerpt, so a follower missed the equaliser's narrative.
`storyline-policy.repair.author_trim` (seed: true) removes only the sentences whose claims still fail after
the rewrites, when the rest passes the grounding rules; false drops the excerpt as before. The engine requires
the key. A key already present (a /dev/ edit) is kept; a changed row gets a new revision.
"""
import json
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent


def migrate(conn):
    seed = json.loads((HERE / 'seeds' / 'storyline-policy.json').read_text(encoding='utf-8'))['repair']
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'").fetchone()
    if row is None:
        return
    repair = row['document'].setdefault('repair', {})
    if 'author_trim' not in repair:
        repair['author_trim'] = seed['author_trim']
        conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'storyline-policy'",
                     (Jsonb(row['document']),))
