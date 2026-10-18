"""Separate local projection store; replace with Cosmos without changing GraphQL."""
import psycopg
from psycopg.types.json import Jsonb


class StatsRepository:
    def __init__(self, dsn):
        self.dsn = dsn

    def initialize(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS demo_stat_projections (
                snapshot_id text PRIMARY KEY, match_id text NOT NULL, stats jsonb NOT NULL)''')
            conn.execute('''CREATE OR REPLACE VIEW standard_stats AS
                SELECT snapshot_id,match_id,stat->>'id' AS stat_id,stat->>'team_id' AS team_id,
                       stat->'value' AS value,(stat->>'available')::boolean AS available,stat
                FROM demo_stat_projections CROSS JOIN LATERAL jsonb_array_elements(stats) stat''')

    def save(self, snapshot_id, match_id, stats):
        with psycopg.connect(self.dsn) as conn:
            conn.execute('INSERT INTO demo_stat_projections VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                         (snapshot_id,match_id,Jsonb(stats)))

    def read(self, snapshot_id):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute('SELECT stats FROM demo_stat_projections WHERE snapshot_id=%s',(snapshot_id,)).fetchone()
        if row is None:
            raise KeyError('Projection unavailable; retry snapshot publication')
        return row[0]
