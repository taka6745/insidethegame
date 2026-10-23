"""The result claim reads a half-time score as where the match stands.

At half time the decision model took "Redcastle Town lead 1-0 at half-time" for how the match ended, so every
period-end wrap-up that gave the score was dropped. `storyline-policy.claims.result.claim` gets the seed's
wording where it is still as 030 seeded it (an edited claim is kept). A changed row gets a new revision.
"""
import json
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent
SEEDED_030 = ('Does this sentence state or imply how the match ended, for example who won, lost or drew it, '
              'or the final score?')


def result(doc, seed):
    claim = (doc.get('claims') or {}).get('result')
    if claim is None or claim.get('claim') != SEEDED_030:
        return False
    claim['claim'] = seed['claim']
    return True


def migrate(conn):
    seed = json.loads((HERE / 'seeds' / 'storyline-policy.json').read_text(encoding='utf-8'))['claims']['result']
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'").fetchone()
    if row is not None and result(row['document'], seed):
        conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'storyline-policy'",
                     (Jsonb(row['document']),))
