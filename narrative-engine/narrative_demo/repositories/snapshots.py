"""Development persistence. Replace with Cosmos without changing HTTP/services."""
import json
import sqlite3
from pathlib import Path


class SnapshotRepository:
    def __init__(self, path):
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('''CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, document TEXT NOT NULL)''')
        self.connection.execute('CREATE TABLE IF NOT EXISTS delivery_state (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL)')
        self.connection.commit()

    def save(self, snapshot_id, run_id, document):
        with self.connection:
            self.connection.execute('INSERT INTO snapshots VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                                    (snapshot_id, run_id, json.dumps(document)))

    def read(self, snapshot_id):
        row = self.connection.execute('SELECT document FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError('Snapshot has not been observed by the narrative service')
        return json.loads(row[0])

    def delivery_state(self):
        row = self.connection.execute('SELECT document FROM delivery_state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def save_delivery_state(self, metadata, signature):
        with self.connection:
            self.connection.execute('INSERT INTO delivery_state VALUES (1,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                                    (json.dumps({'metadata': metadata, 'signature': signature}),))

    def close(self):
        self.connection.close()
