"""Audience templates per feed fixture (configuration) and each match's catalogue.

A match's catalogue copies its fixture's template (else the default); the template's `enabled`
flags alone choose generation targets. Every change to a match's document bumps its revision,
which the narrative engine polls."""
from psycopg.types.json import Jsonb

from backend.domain import RuleError
from backend.models.audiences import AudienceConfig

DEFAULT = 'default'


class AudienceRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _template(conn, fixture, *, lock=False):
        """The fixture's own template, else the default one: (row, inherited)."""
        suffix = ' FOR UPDATE' if lock else ''
        row = conn.execute('SELECT * FROM audience_templates WHERE fixture=%s' + suffix, (fixture,)).fetchone()
        if row is not None:
            return row, False
        return conn.execute('SELECT * FROM audience_templates WHERE fixture=%s' + suffix, (DEFAULT,)).fetchone(), True

    def template(self, fixture):
        with self.store.connect() as conn:
            row, inherited = self._template(conn, fixture)
        return {'fixture': fixture, 'inherited': inherited, 'revision': row['revision'],
                'config': AudienceConfig.model_validate(row['document'])}

    @staticmethod
    def _apply(conn, match_id, template):
        """Copy the template into one match's document; bump the revision only on change."""
        conn.execute('UPDATE audience_catalog SET document=%s, revision=revision+1 WHERE match_id=%s AND document<>%s',
                     (Jsonb(template['document']), match_id, Jsonb(template['document'])))

    def ensure(self, match_id, fixture):
        """Create the match's catalogue from its fixture template."""
        with self.store.connect() as conn:
            template, _ = self._template(conn, fixture)
            conn.execute('INSERT INTO audience_catalog (match_id, fixture, document) '
                         'SELECT %s,%s,%s WHERE EXISTS (SELECT 1 FROM received_matches WHERE match_id=%s) '
                         'ON CONFLICT DO NOTHING', (match_id, fixture, Jsonb(template['document']), match_id))

    def replace_template(self, fixture, config, expected_revision):
        with self.store.connect() as conn:
            # One template writer per fixture, also while its row does not exist yet.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('audience-template:' || %s))", (fixture,))
            row, inherited = self._template(conn, fixture, lock=True)
            if row['revision'] != expected_revision:
                raise RuleError('audience_revision_conflict', 'Reload the catalogue before editing', 409)
            document = config.model_dump()
            if not inherited and fixture != DEFAULT:
                default = conn.execute('SELECT * FROM audience_templates WHERE fixture=%s', (DEFAULT,)).fetchone()
                if document == AudienceConfig.model_validate(default['document']).model_dump():
                    # An own copy edited back to the default inherits it again.
                    conn.execute('DELETE FROM audience_templates WHERE fixture=%s', (fixture,))
                    for match in conn.execute('SELECT match_id FROM audience_catalog WHERE fixture=%s', (fixture,)).fetchall():
                        self._apply(conn, match['match_id'], default)
                    return default['revision']
            saved = conn.execute('INSERT INTO audience_templates (fixture, revision, document) VALUES (%s,%s,%s) '
                                 'ON CONFLICT (fixture) DO UPDATE SET revision=EXCLUDED.revision, document=EXCLUDED.document '
                                 'RETURNING *', (fixture, row['revision'] + 1, Jsonb(document))).fetchone()
            # Every match using this template (the default serves fixtures without their own).
            matches = conn.execute('SELECT match_id FROM audience_catalog WHERE fixture=%s OR (%s AND fixture NOT IN '
                                   '(SELECT fixture FROM audience_templates))', (fixture, fixture == DEFAULT)).fetchall()
            for match in matches:
                self._apply(conn, match['match_id'], saved)
            return saved['revision']

    def templates(self):
        """Every template, and each match's fixture and enabled buckets."""
        with self.store.connect() as conn:
            templates = conn.execute('SELECT fixture, revision FROM audience_templates ORDER BY fixture').fetchall()
            matches = conn.execute('SELECT match_id, fixture, revision, document FROM audience_catalog '
                                   'ORDER BY match_id').fetchall()
        return {'templates': templates,
                'matches': [{'match_id': m['match_id'], 'fixture': m['fixture'], 'revision': m['revision'],
                             'enabled': [b['id'] for b in m['document']['buckets'] if b['enabled']]} for m in matches]}

    def revision(self, match_id):
        with self.store.connect() as conn:
            row = conn.execute('SELECT revision FROM audience_catalog WHERE match_id=%s', (match_id,)).fetchone()
        if row is None:
            raise RuleError('match_not_found', 'No audience configuration for this match', 404)
        return row['revision']

    def read(self, match_id):
        with self.store.connect() as conn:
            row = conn.execute('SELECT revision, document FROM audience_catalog WHERE match_id=%s', (match_id,)).fetchone()
        if row is None:
            raise RuleError('match_not_found', 'No audience configuration for this match', 404)
        return AudienceConfig.model_validate(row['document']), row['revision']
