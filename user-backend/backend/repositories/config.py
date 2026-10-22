"""backend_config rows: one validated document per name, optimistic revision updates."""
from psycopg.types.json import Jsonb

from backend.domain import RuleError


class ConfigRepository:
    def __init__(self, store):
        self.store = store

    def read_all(self):
        with self.store.connect() as conn:
            return {row['name']: (row['revision'], row['document'])
                    for row in conn.execute('SELECT name, revision, document FROM backend_config')}

    def revisions(self):
        with self.store.connect() as conn:
            return {row['name']: row['revision'] for row in conn.execute('SELECT name, revision FROM backend_config')}

    def replace(self, name, document, expected_revision):
        with self.store.connect() as conn:
            row = conn.execute('UPDATE backend_config SET document=%s, revision=revision+1 '
                               'WHERE name=%s AND revision=%s RETURNING revision',
                               (Jsonb(document), name, expected_revision)).fetchone()
        if row is None:
            raise RuleError('config_revision_conflict', 'Reload the configuration before saving', 409)
        return row['revision']
