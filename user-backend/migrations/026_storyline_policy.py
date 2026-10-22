"""The storyline policy (engine stream S3): every tunable of the engine's analysis, storylines and repair turns.

Seeds `backend_config` row `storyline-policy` from migrations/seeds/storyline-policy.json (the engine ships a byte
copy for its tests). Served to the engine at GET /storyline-policy and edited under /dev/config/storyline-policy;
an existing row (a /dev/ edit) is kept.
"""
from pathlib import Path

from psycopg.types.json import Jsonb

SEED = Path(__file__).parent / 'seeds' / 'storyline-policy.json'


def migrate(conn):
    import json
    conn.execute("INSERT INTO backend_config (name, document) VALUES ('storyline-policy', %s) ON CONFLICT DO NOTHING",
                 (Jsonb(json.loads(SEED.read_text(encoding='utf-8'))),))
