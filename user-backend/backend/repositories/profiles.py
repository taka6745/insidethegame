"""Demo profiles (Accounts database) as one revision-checked set."""
from psycopg.types.json import Jsonb

from backend.domain import RuleError


class ProfileRepository:
    def __init__(self, store):
        self.store = store

    def read(self):
        with self.store.connect_accounts() as conn:
            revision = conn.execute('SELECT revision FROM demo_profile_revision').fetchone()['revision']
            profiles = conn.execute('SELECT id, display_name, selections FROM demo_profiles ORDER BY id').fetchall()
        return revision, profiles

    def replace(self, profiles, expected_revision):
        """Replace the whole set; sessions of a removed profile are refused until they choose another."""
        with self.store.connect_accounts() as conn:
            row = conn.execute('UPDATE demo_profile_revision SET revision=revision+1 WHERE revision=%s RETURNING revision',
                               (expected_revision,)).fetchone()
            if row is None:
                raise RuleError('profiles_revision_conflict', 'Reload the profiles before saving', 409)
            conn.execute('DELETE FROM demo_profiles WHERE NOT (id = ANY(%s))', ([p['id'] for p in profiles],))
            with conn.cursor() as cursor:
                cursor.executemany('INSERT INTO demo_profiles (id, display_name, selections) VALUES (%s,%s,%s) '
                                   'ON CONFLICT (id) DO UPDATE SET display_name=EXCLUDED.display_name, '
                                   'selections=EXCLUDED.selections',
                                   [(p['id'], p['display_name'], Jsonb(p['selections'])) for p in profiles])
        return row['revision']
