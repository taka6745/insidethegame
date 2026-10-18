"""Owns audience configuration, source narratives and reusable framed variants."""
from pathlib import Path

from psycopg.types.json import Jsonb

from ..domain import RuleError
from ..models.narratives import AudienceConfig


class NarrativeRepository:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        root = Path(__file__).parents[2]
        seed = AudienceConfig.model_validate_json((root / 'fixtures/narratives/audiences.json').read_text())
        with self.store.connect() as conn:
            conn.execute((root / 'migrations/004_narrative_framing.sql').read_text())
            conn.execute('INSERT INTO audience_config(document) VALUES (%s) ON CONFLICT DO NOTHING',
                         (Jsonb(seed.model_dump()),))

    def change_viewer(self, token, match_id, update):
        return self.store.change(token, match_id, update)

    def config(self):
        with self.store.connect() as conn:
            row = conn.execute('SELECT document,revision FROM audience_config').fetchone()
        return AudienceConfig.model_validate(row['document']), row['revision']

    def configure(self, config, expected_revision):
        with self.store.connect() as conn:
            row = conn.execute('UPDATE audience_config SET document=%s,revision=revision+1 '
                               'WHERE revision=%s RETURNING revision',
                               (Jsonb(config.model_dump()), expected_revision)).fetchone()
            if row is None:
                raise RuleError('config_conflict', 'Reload the audience configuration before editing', 409)
        return row['revision']

    def record(self, narrative):
        doc = narrative.model_dump()
        key = (narrative.match_id, narrative.id, narrative.revision)
        with self.store.connect() as conn:
            conn.execute('INSERT INTO neutral_narratives VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (*key, Jsonb(doc)))
            saved = conn.execute('SELECT document FROM neutral_narratives WHERE match_id=%s '
                                 'AND narrative_id=%s AND revision=%s', key).fetchone()
            if saved['document'] != doc:
                raise RuleError('narrative_conflict', 'Changed content requires a new narrative revision', 422)
            latest = conn.execute('SELECT max(revision) AS revision FROM neutral_narratives '
                                  'WHERE match_id=%s AND narrative_id=%s', key[:2]).fetchone()
        return latest['revision'] == narrative.revision

    def claim(self, narrative, owner, seconds):
        with self.store.connect() as conn:
            row = conn.execute('INSERT INTO narrative_framing_leases VALUES (%s,%s,%s,now()+%s*interval \'1 second\') '
                               'ON CONFLICT (match_id,narrative_id) DO UPDATE SET owner=EXCLUDED.owner, '
                               'expires_at=EXCLUDED.expires_at WHERE narrative_framing_leases.expires_at<now() '
                               'RETURNING owner', (narrative.match_id, narrative.id, owner, seconds)).fetchone()
        return row is not None

    def release(self, narrative, owner):
        with self.store.connect() as conn:
            conn.execute('DELETE FROM narrative_framing_leases WHERE match_id=%s AND narrative_id=%s AND owner=%s',
                         (narrative.match_id, narrative.id, owner))

    def cached(self, narrative):
        with self.store.connect() as conn:
            return conn.execute('SELECT bucket_id,framing_key,text,mode FROM narrative_variants '
                                'WHERE match_id=%s AND narrative_id=%s AND revision=%s',
                                (narrative.match_id, narrative.id, narrative.revision)).fetchall()

    def save(self, narrative, variants):
        with self.store.connect() as conn:
            for item in variants:
                conn.execute('INSERT INTO narrative_variants VALUES (%s,%s,%s,%s,%s,%s,%s) '
                             'ON CONFLICT DO NOTHING',
                             (narrative.match_id, narrative.id, narrative.revision,
                              item['bucket_id'], item['framing_key'], item['text'], item['mode']))

    def history(self, match_id, bucket_id, framing_key):
        with self.store.connect() as conn:
            return conn.execute('SELECT n.document AS source,v.text,v.bucket_id,v.mode FROM neutral_narratives n '
                                'JOIN narrative_variants v USING(match_id,narrative_id,revision) '
                                'WHERE n.match_id=%s AND v.bucket_id=%s AND v.framing_key=%s '
                                'AND n.revision=(SELECT max(x.revision) FROM neutral_narratives x '
                                'WHERE x.match_id=n.match_id AND x.narrative_id=n.narrative_id) '
                                "ORDER BY (n.document->>'minute')::int,n.narrative_id LIMIT 200",
                                (match_id, bucket_id, framing_key)).fetchall()
