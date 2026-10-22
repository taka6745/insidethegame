"""Round 17: a storyline label's score claim is checked, and a resolved storyline can reopen.

Live, the label "Arsenal's late equalizer" passed every check though the goal made it 1-0, and a storyline
resolved at 45' came back at 50' as a second one with the same label. `storyline-policy.claims.score` asks
the decision model whether a sentence states a score or what a goal did to it, and whether the ledger (which
now gives the score after each goal) shows it; `storylines.reopen_within` (minutes) reopens a resolved storyline
of the same label instead of opening another. The engine requires both. Keys already present (a /dev/ edit)
are kept; a changed row gets a new revision.
"""
import json
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent


def migrate(conn):
    seed = json.loads((HERE / 'seeds' / 'storyline-policy.json').read_text(encoding='utf-8'))
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'storyline-policy'").fetchone()
    if row is None:
        return
    doc, changed = row['document'], False
    for section, key in (('storylines', 'reopen_within'), ('claims', 'score')):
        if key not in doc.setdefault(section, {}):
            doc[section][key], changed = seed[section][key], True
    if changed:
        conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'storyline-policy'",
                     (Jsonb(doc),))
