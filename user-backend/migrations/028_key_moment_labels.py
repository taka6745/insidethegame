"""Key-moment labels: "Goal · {team} · {scorer}", "Red card · {player}",
"Half time · {score}", plus the `score` template the {score} field uses. Rewrites `key-moment-feed` labels that
still equal the 024 seed; edited labels (a /dev/ change) are kept. A changed row gets a new revision."""
import importlib.util
from pathlib import Path

from psycopg.types.json import Jsonb

OLD = {'goal': 'Goal · {subject}', 'red_card': 'Red card · {subject}', 'second_yellow': 'Second yellow · {subject}',
       'half_time': 'Half-time', 'full_time': 'Full-time'}


def migrate(conn):
    spec = importlib.util.spec_from_file_location('m024', Path(__file__).parent / '024_subscriptions.py')
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    row = conn.execute("SELECT document FROM backend_config WHERE name = 'key-moment-feed'").fetchone()
    if row is None:
        return
    document = row['document']
    labels, changed = document.setdefault('labels', {}), 'score' not in document
    document.setdefault('score', seed.SCORE)
    for kind, old in OLD.items():
        if labels.get(kind) == old:
            labels[kind], changed = seed.LABELS[kind], True
    if changed:
        conn.execute("UPDATE backend_config SET document = %s, revision = revision + 1 WHERE name = 'key-moment-feed'",
                     (Jsonb(document),))
