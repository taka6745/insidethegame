"""Round 16: the comparison claim reads the evidence as the writer did.

Live drops showed the 030 wording rejecting comparisons a storyline outcome stated in words ("faded"), a single
value called high, and a lower-is-more indicator read the right way. `storyline-policy.claims.comparison` gets the
seed's `claim`, `support` and `repair` where it is still as 030 seeded it (an edited claim is kept).
A changed row gets a new revision.
"""
import json
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent
TEXTS = ('claim', 'support', 'repair')
SEEDED_030 = {
    'claim': 'Does this sentence compare the two teams, or a team with itself earlier, saying that one is higher, '
             'deeper, more, less, better or worse than the other?',
    'support': 'Do the numbers in the evidence above show that comparison in the same direction?',
    'repair': 'states a comparison the numbers shown do not support in that direction; check which value is higher, '
              'or leave the comparison out',
}


def comparison(doc, seed):
    claim = (doc.get('claims') or {}).get('comparison')
    if claim is None or {k: claim.get(k) for k in TEXTS} != SEEDED_030:
        return False
    claim |= {k: seed[k] for k in TEXTS}
    return True


def migrate(conn):
    seed = json.loads((HERE / 'seeds' / 'storyline-policy.json').read_text(encoding='utf-8'))['claims']['comparison']
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'").fetchone()
    if row is not None and comparison(row['document'], seed):
        conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'storyline-policy'",
                     (Jsonb(row['document']),))
