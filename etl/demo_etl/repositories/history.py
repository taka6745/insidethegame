"""Local PostgreSQL history substitute; production Azure SQL adapter is separate."""
import psycopg
from psycopg.types.json import Jsonb
from demo_etl.models.snapshot import SnapshotInput


class HistoryRepository:
    def __init__(self, dsn):
        self.dsn = dsn

    def initialize(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS demo_runs (
                run_id text PRIMARY KEY, recording_hash text NOT NULL, catalogue jsonb NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS demo_deliveries (
                run_id text REFERENCES demo_runs(run_id), position integer NOT NULL, event jsonb NOT NULL,
                PRIMARY KEY(run_id, position))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS demo_snapshots (
                id text PRIMARY KEY, run_id text REFERENCES demo_runs(run_id), cursor integer NOT NULL,
                metadata jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())''')
            conn.execute('''CREATE OR REPLACE VIEW raw_event_history AS
                SELECT run_id, position, event->>'event_id' AS event_id,
                (event->>'revision')::integer AS revision, event FROM demo_deliveries''')

    def save_recording(self, source):
        # Original provider-inspired JSON is retained once, separately from normalized history.
        with psycopg.connect(self.dsn) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS demo_recordings (hash text PRIMARY KEY, document jsonb NOT NULL)")
            conn.execute("INSERT INTO demo_recordings VALUES (%s,%s) ON CONFLICT DO NOTHING",(source.fingerprint,Jsonb(source.document)))
            conn.execute("""CREATE OR REPLACE VIEW raw_recording_events AS
                SELECT hash AS recording_hash, position, payload FROM demo_recordings
                CROSS JOIN LATERAL jsonb_array_elements(document->'events') WITH ORDINALITY AS e(payload,position)""")

    def save(self, payload):
        meta = payload.model_dump(mode='json', exclude={'events'})
        catalogue = {key: meta[key] for key in ('teams','players','data_reference')}
        run = payload.snapshot.run_id
        with psycopg.connect(self.dsn) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (run,))
            row = conn.execute('SELECT recording_hash,catalogue FROM demo_runs WHERE run_id=%s', (run,)).fetchone()
            if row and (row[0] != payload.snapshot.recording_hash or row[1] != catalogue):
                raise ValueError('Run identity or catalogue cannot change')
            conn.execute('INSERT INTO demo_runs VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                         (run,payload.snapshot.recording_hash,Jsonb(catalogue)))
            # Deliveries are append-only: the stored count and its last row identify the prefix,
            # so a publish costs only its new deliveries, not a rescan of the whole match.
            stored = conn.execute('SELECT count(*) FROM demo_deliveries WHERE run_id=%s', (run,)).fetchone()[0]
            common = min(stored, payload.snapshot.cursor)
            if common:
                last = conn.execute('SELECT event FROM demo_deliveries WHERE run_id=%s AND position=%s',
                                    (run, common)).fetchone()[0]
                if last != payload.events[common-1].model_dump(mode='json'):
                    raise ValueError('A published delivery prefix is immutable')
            with conn.cursor() as cursor:
                cursor.executemany('INSERT INTO demo_deliveries VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                    [(run,index+1,Jsonb(e.model_dump(mode='json'))) for index,e in enumerate(payload.events) if index >= stored])
            conn.execute('INSERT INTO demo_snapshots (id,run_id,cursor,metadata) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (payload.snapshot.id,run,payload.snapshot.cursor,Jsonb(meta)))

    def metadata(self, snapshot_id):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute('SELECT metadata FROM demo_snapshots WHERE id=%s',(snapshot_id,)).fetchone()
        if not row:
            raise KeyError('Snapshot unavailable')
        return row[0]

    def read(self, snapshot_id):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute('SELECT run_id,cursor,metadata FROM demo_snapshots WHERE id=%s',(snapshot_id,)).fetchone()
            if not row:
                raise KeyError('Snapshot unavailable')
            events = [r[0] for r in conn.execute('SELECT event FROM demo_deliveries WHERE run_id=%s AND position<=%s ORDER BY position',(row[0],row[1]))]
        return SnapshotInput.model_validate({**row[2], 'events': events})

    def latest(self, match_id):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute("SELECT id FROM demo_snapshots WHERE metadata->'snapshot'->>'match_id'=%s ORDER BY created_at DESC LIMIT 1",(match_id,)).fetchone()
        if not row:
            raise KeyError('Match unavailable')
        return self.read(row[0])
