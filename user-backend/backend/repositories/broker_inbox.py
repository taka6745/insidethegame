"""Durable acceptance before Service Bus settlement; narrative content stays upstream-owned."""
from pathlib import Path
from psycopg.types.json import Jsonb


class NarrativeInbox:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.connect() as conn:
            for name in ('009_broker_inbox.sql', '010_inbox_cursor.sql'):
                conn.execute((Path(__file__).parents[2] / 'migrations' / name).read_text())

    def save(self, delivery):
        with self.store.connect() as conn:
            cursor = conn.execute('''INSERT INTO broker_narrative_inbox
                (snapshot_id, run_id, audience_revision, document, snapshot_cursor) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(snapshot_id) DO UPDATE SET audience_revision=EXCLUDED.audience_revision,
                document=EXCLUDED.document
                WHERE broker_narrative_inbox.audience_revision < EXCLUDED.audience_revision''',
                (delivery.snapshot.id, delivery.snapshot.run_id, delivery.audience_revision,
                 Jsonb(delivery.document()), delivery.snapshot.cursor))
            return cursor.rowcount == 1

    def read(self, snapshot_id):
        with self.store.connect() as conn:
            row = conn.execute('SELECT document FROM broker_narrative_inbox WHERE snapshot_id=%s',
                               (snapshot_id,)).fetchone()
        return row['document'] if row else None

    def latest_cursor(self, run_id, at_most):
        """Newest cursor of this run the narrative service has delivered, at or before at_most."""
        with self.store.connect() as conn:
            row = conn.execute('''SELECT max(snapshot_cursor) AS cursor FROM broker_narrative_inbox
                WHERE run_id=%s AND snapshot_cursor<=%s''', (run_id, at_most)).fetchone()
        return row['cursor']
