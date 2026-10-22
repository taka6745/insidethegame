"""Append-only prompt versions with an optimistic active pointer per role."""
from pathlib import Path

from ..domain import RuleError
from ..models.prompts import ROLES, placeholders

SEEDS = Path(__file__).parents[2] / 'migrations/prompts'  # Version 1 of each role; shipped with the migrations.
ACTIVE = ('SELECT p.role,p.version,p.template,p.placeholders FROM narrative_prompt_active a '
          'JOIN narrative_prompts p USING (role,version) ORDER BY p.role')


class PromptRepository:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.connect() as conn:
            for role in ROLES:
                template = (SEEDS / f'{role}.txt').read_text(encoding='utf-8')
                conn.execute('INSERT INTO narrative_prompts(role,version,template,placeholders,source) '
                             "VALUES (%s,1,%s,%s,'seed') ON CONFLICT DO NOTHING",
                             (role, template, placeholders(template)))
                conn.execute('INSERT INTO narrative_prompt_active(role,version,revision) VALUES (%s,1,1) '
                             'ON CONFLICT DO NOTHING', (role,))

    def active(self):
        with self.store.connect() as conn:
            revision = conn.execute('SELECT max(revision) AS r FROM narrative_prompt_active').fetchone()['r']
            return revision, conn.execute(ACTIVE).fetchall()

    def versions(self, limit=50):
        with self.store.connect() as conn:
            active = {r['role']: r['version'] for r in conn.execute('SELECT role,version FROM narrative_prompt_active')}
            rows = conn.execute('SELECT role,version,template,placeholders,source,created_at FROM ('
                                'SELECT *, row_number() OVER (PARTITION BY role ORDER BY version DESC) AS n '
                                'FROM narrative_prompts) v WHERE n<=%s ORDER BY role,version DESC', (limit,)).fetchall()
        return active, rows

    def save(self, role, template, expected_version):
        with self.store.connect() as conn:
            current = self._lock(conn, role)
            if current['version'] != expected_version:
                raise RuleError('prompt_version_conflict', 'Reload the prompt before saving', 409)
            if placeholders(template) != current['placeholders']:
                raise RuleError('prompt_placeholders', 'Keep exactly these placeholders: '
                                + ', '.join('{' + p + '}' for p in current['placeholders']), 422)
            version = conn.execute('INSERT INTO narrative_prompts(role,version,template,placeholders,source) '
                                   "SELECT %s,max(version)+1,%s,%s,'dev' FROM narrative_prompts WHERE role=%s "
                                   'RETURNING version', (role, template, current['placeholders'], role)).fetchone()['version']
            return self._point(conn, role, version)

    def activate(self, role, version):
        with self.store.connect() as conn:
            self._lock(conn, role)
            if not conn.execute('SELECT 1 FROM narrative_prompts WHERE role=%s AND version=%s', (role, version)).fetchone():
                raise RuleError('prompt_version_not_found', 'Unknown prompt version', 404)
            return self._point(conn, role, version)

    @staticmethod
    def _lock(conn, role):
        # One writer at a time keeps the global revision strictly increasing.
        conn.execute('LOCK TABLE narrative_prompt_active IN SHARE ROW EXCLUSIVE MODE')
        return conn.execute('SELECT a.version,p.placeholders FROM narrative_prompt_active a '
                            'JOIN narrative_prompts p USING (role,version) WHERE role=%s', (role,)).fetchone()

    @staticmethod
    def _point(conn, role, version):
        conn.execute('UPDATE narrative_prompt_active SET version=%s,'
                     'revision=(SELECT max(revision)+1 FROM narrative_prompt_active) WHERE role=%s', (version, role))
        return version
