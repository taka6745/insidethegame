"""Match App persistence for audience configuration, with optimistic updates."""
from pathlib import Path

from psycopg.types.json import Jsonb

from ..domain import RuleError
from ..models.audiences import AudienceConfig


class AudienceRepository:
    def __init__(self, store):
        self.store = store

    def initialize(self, match_id):
        root = Path(__file__).parents[2]
        seed = AudienceConfig.model_validate_json((root / 'fixtures/audiences.json').read_text())
        with self.store.connect() as conn:
            conn.execute((root / 'migrations/005_audience_catalog.sql').read_text())
            conn.execute('INSERT INTO audience_catalog(match_id,document) VALUES (%s,%s) '
                         'ON CONFLICT DO NOTHING', (match_id, Jsonb(seed.model_dump())))

    def read(self, match_id):
        with self.store.connect() as conn:
            row = conn.execute('SELECT revision,document FROM audience_catalog WHERE match_id=%s',
                               (match_id,)).fetchone()
        if row is None:
            raise RuleError('match_not_found', 'No audience configuration for this match', 404)
        return AudienceConfig.model_validate(row['document']), row['revision']

    def replace(self, match_id, config, expected_revision):
        with self.store.connect() as conn:
            row = conn.execute('UPDATE audience_catalog SET document=%s,revision=revision+1 '
                               'WHERE match_id=%s AND revision=%s RETURNING revision',
                               (Jsonb(config.model_dump()), match_id, expected_revision)).fetchone()
        if row is None:
            raise RuleError('audience_revision_conflict', 'Reload the catalogue before editing', 409)
        return row['revision']
