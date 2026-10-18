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
            conn.execute((root / 'migrations/008_audience_presence.sql').read_text())
            conn.execute('INSERT INTO audience_catalog(match_id,document) VALUES (%s,%s) '
                         'ON CONFLICT DO NOTHING', (match_id, Jsonb(seed.model_dump())))

    def clear_viewer_targets(self):
        """Only the one local product owner uses presence-managed catalogues."""
        with self.store.connect() as conn:
            rows = conn.execute('SELECT match_id,document FROM audience_catalog WHERE viewer_managed FOR UPDATE').fetchall()
            for row in rows:
                self._set_enabled(conn, row['match_id'], row['document'], set())

    def set_viewer_targets(self, match_id, selections):
        root = Path(__file__).parents[2]
        seed = AudienceConfig.model_validate_json((root / 'fixtures/audiences.json').read_text())
        for bucket in seed.buckets:
            bucket.enabled = False
        with self.store.connect() as conn:
            conn.execute('INSERT INTO audience_catalog(match_id,document,viewer_managed) VALUES (%s,%s,true) '
                         'ON CONFLICT(match_id) DO UPDATE SET viewer_managed=true',
                         (match_id, Jsonb(seed.model_dump())))
            row = conn.execute('SELECT document FROM audience_catalog WHERE match_id=%s FOR UPDATE',
                               (match_id,)).fetchone()
            self._set_enabled(conn, match_id, row['document'], selections)

    @staticmethod
    def _set_enabled(conn, match_id, document, selections):
        changed = False
        for bucket in document['buckets']:
            choice = bucket['selections']
            enabled = (set(choice) == {'team', 'fan_style'} and
                       (choice['team'], choice['fan_style']) in selections)
            changed |= bucket['enabled'] != enabled
            bucket['enabled'] = enabled
        if changed:
            conn.execute('UPDATE audience_catalog SET document=%s,revision=revision+1 WHERE match_id=%s',
                         (Jsonb(document), match_id))

    def read(self, match_id):
        with self.store.connect() as conn:
            row = conn.execute('SELECT revision,document FROM audience_catalog WHERE match_id=%s',
                               (match_id,)).fetchone()
        if row is None:
            raise RuleError('match_not_found', 'No audience configuration for this match', 404)
        return AudienceConfig.model_validate(row['document']), row['revision']

    def replace(self, match_id, config, expected_revision):
        with self.store.connect() as conn:
            current = conn.execute('SELECT document,viewer_managed FROM audience_catalog WHERE match_id=%s FOR UPDATE',
                                   (match_id,)).fetchone()
            if current and current['viewer_managed']:
                active = [bucket['selections'] for bucket in current['document']['buckets'] if bucket['enabled']]
                config = config.model_copy(deep=True)
                for bucket in config.buckets:
                    bucket.enabled = bucket.selections in active
            row = conn.execute('UPDATE audience_catalog SET document=%s,revision=revision+1 '
                               'WHERE match_id=%s AND revision=%s RETURNING revision',
                               (Jsonb(config.model_dump()), match_id, expected_revision)).fetchone()
        if row is None:
            raise RuleError('audience_revision_conflict', 'Reload the catalogue before editing', 409)
        return row['revision']
