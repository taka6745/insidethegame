"""A viewer's "story so far" dropped as ungrounded is tried again; analyst labels face the intent check.

- `subscriptions.catch_up.retries`, from 024's seed (the engine requires it).
- `storyline-policy.claims.intent.analyst` becomes true where the intent claim is still as seeded (an edited
  claim is kept), so an analyst label or observation that states intent is checked like an excerpt.
A changed row gets a new revision.
"""
import importlib.util
import json
from pathlib import Path

from psycopg.types.json import Jsonb

HERE = Path(__file__).parent


def _patch(conn, name, change):
    row = conn.execute('SELECT document FROM backend_config WHERE name = %s', (name,)).fetchone()
    if row is not None and change(row['document']):
        conn.execute('UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = %s',
                     (Jsonb(row['document']), name))


def _retries(doc, value):
    section = doc.setdefault('catch_up', {})
    if 'retries' in section:
        return False
    section['retries'] = value
    return True


def _intent(doc, seeded):
    intent = (doc.get('claims') or {}).get('intent')
    if intent is None or intent.get('analyst') or {k: v for k, v in intent.items() if k != 'analyst'} != seeded:
        return False
    intent['analyst'] = True
    return True


def migrate(conn):
    spec = importlib.util.spec_from_file_location('m024', HERE / '024_subscriptions.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    intent = json.loads((HERE / 'seeds' / 'storyline-policy.json').read_text(encoding='utf-8'))['claims']['intent']
    _patch(conn, 'subscriptions', lambda doc: _retries(doc, seed.CONFIG['subscriptions']['catch_up']['retries']))
    _patch(conn, 'storyline-policy',
           lambda doc: _intent(doc, {k: v for k, v in intent.items() if k != 'analyst'}))
