"""Replay timing keys move to SPADL: clips are cut around SPADL actions and MA3 cards.

Each old canonical key's seconds go to the SPADL types it covers; `goal`, `shot`, `card` and `foul`
keep their names; keys with no SPADL action (offside, foul_won, corner_awarded) are dropped.
Edited values are kept: only the key names change."""
import json

from psycopg.types.json import Jsonb

KEYS = {'save': ['keeper_save'], 'penalty': ['shot_penalty'], 'corner': ['corner_crossed', 'corner_short'],
        'free_kick': ['freekick_crossed', 'freekick_short', 'shot_freekick'], 'offside': [], 'foul_won': [],
        'corner_awarded': []}


def remap(document):
    timing = {}
    for key, seconds in document['timing'].items():
        for new in KEYS.get(key, [key]):
            timing.setdefault(new, seconds)
    return {**document, 'timing': timing}


def migrate(conn):
    row = conn.execute("SELECT document FROM backend_config WHERE name='replay-timing'").fetchone()
    if row is None or not set(row['document']['timing']) & set(KEYS):
        return
    conn.execute("UPDATE backend_config SET document=%s, revision=revision+1 WHERE name='replay-timing'",
                 (Jsonb(json.loads(json.dumps(remap(row['document'])))),))
