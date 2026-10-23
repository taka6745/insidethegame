"""The engine's remaining prompt limits and the follow chat's candidate cap become config.

- `storyline-policy.storylines`: `beats_shown`, `resolved_shown_minutes` and `author_match_indicators`, from
  migrations/seeds/storyline-policy.json (the engine requires them).
- `subscriptions.max_candidates`, from 024's seed.
Keys already present (a /dev/ edit) are kept; a changed row gets a new revision.
"""
import importlib.util
import json
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent
KEYS = ('beats_shown', 'resolved_shown_minutes', 'author_match_indicators')


def _patch(conn, name, change):
    row = conn.execute('SELECT document FROM backend_config WHERE name = %s', (name,)).fetchone()
    if row is not None and change(row['document']):
        conn.execute('UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = %s',
                     (Jsonb(row['document']), name))


def _add(section, values):
    missing = [k for k in values if k not in section]
    for key in missing:
        section[key] = values[key]
    return bool(missing)


def migrate(conn):
    lines = json.loads((HERE / 'seeds' / 'storyline-policy.json').read_text(encoding='utf-8'))['storylines']
    spec = importlib.util.spec_from_file_location('m024', HERE / '024_subscriptions.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    cap = seed.CONFIG['subscriptions']['max_candidates']
    _patch(conn, 'storyline-policy',
           lambda doc: _add(doc.setdefault('storylines', {}), {k: lines[k] for k in KEYS}))
    _patch(conn, 'subscriptions', lambda doc: _add(doc, {'max_candidates': cap}))
