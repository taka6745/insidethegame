"""Demo seeds (PLAN.md §10.6): export a match's backend rows, or load them under a new matchId.

Restore writes rows in the shapes the stream consumer writes, then has the registry adopt the match as it
does after a restart, so no core code knows a demo exists. Mounted only with DEMO_SEEDS=1."""
import asyncio
import hashlib
import json
from datetime import datetime

from fastapi import APIRouter
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from backend.domain import RuleError

# Parents first: the match, what arrived on its stream, its audience catalogue and the engine's narratives.
# Viewers' sessions, follows, questions and calculations are theirs and are never seeded.
SEED_TABLES = ('received_matches', 'received_events', 'match_gaps', 'audience_catalog', 'engine_narratives',
               'narrative_clips')


class SeedRefused(ValueError):
    pass


class SeedExport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    match_id: str = Field(min_length=1, max_length=64)


class SeedRestore(SeedExport):
    max_seq: int = Field(ge=0)
    schema_: str = Field(alias='schema', min_length=1, max_length=64)  # the export's schema fingerprint
    tables: dict[str, list[dict]]


def _value(value):
    return value.isoformat() if isinstance(value, datetime) else value


class SeedRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _schema(conn):
        """Fingerprint of the seeded tables' columns: a seed restores only into the schema it came from."""
        columns = [[r['table_name'], r['column_name'], r['data_type']] for r in conn.execute(
            'SELECT table_name, column_name, data_type FROM information_schema.columns '
            'WHERE table_schema=current_schema() AND table_name = ANY(%s) ORDER BY table_name, column_name',
            (list(SEED_TABLES),))]
        return hashlib.sha256(json.dumps(columns).encode()).hexdigest()[:16]

    def export(self, match_id):
        with self.store.connect() as conn:
            return self._schema(conn), {table: [{k: _value(v) for k, v in row.items()} for row in conn.execute(
                sql.SQL('SELECT * FROM {} WHERE match_id=%s').format(sql.Identifier(table)), (match_id,))]
                for table in SEED_TABLES}

    def restore(self, match_id, tables, max_seq, schema):
        """Insert a seed under a new matchId in one transaction; refused for another schema, a known or
        tombstoned match, rows of another match or anything past the seed's seq."""
        if set(tables) - set(SEED_TABLES):
            raise SeedRefused(f'Unknown tables {sorted(set(tables) - set(SEED_TABLES))}')
        if any(row.get('match_id') != match_id for rows in tables.values() for row in rows):
            raise SeedRefused('The seed holds rows of another match')
        for table, column in (('received_events', 'seq'), ('match_gaps', 'seq'), ('narrative_clips', 'event_seq'),
                              ('engine_narratives', 'event_seq')):
            if any((row.get(column) or 0) > max_seq for row in tables.get(table, [])):
                raise SeedRefused(f"{table} past the seed's seq")
        if len(tables.get('received_matches', [])) != 1:
            raise SeedRefused('A seed holds exactly one received match')
        with self.store.connect() as conn:
            if self._schema(conn) != schema:
                raise SeedRefused('The seed was exported from another backend schema; record it again')
            if conn.execute('SELECT 1 FROM match_tombstones WHERE match_id=%s UNION ALL '
                            'SELECT 1 FROM received_matches WHERE match_id=%s', (match_id, match_id)).fetchone():
                raise SeedRefused(f'{match_id} is already known or purged')
            jsonb = {(r['table_name'], r['column_name']) for r in conn.execute(
                "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                "AND data_type='jsonb'")}
            counts = {}
            with conn.cursor() as cursor:
                for table in SEED_TABLES:
                    rows = tables.get(table, [])
                    for columns in {tuple(row) for row in rows}:  # COPY: one round trip per table
                        statement = sql.SQL('COPY {} ({}) FROM STDIN').format(
                            sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, columns)))
                        with cursor.copy(statement) as copy:
                            for row in rows:
                                if tuple(row) == columns:
                                    copy.write_row(tuple(Jsonb(row[c]) if (table, c) in jsonb else row[c]
                                                         for c in columns))
                    counts[table] = len(rows)
            return counts


def demo_seed_router(registry, repository):
    router = APIRouter(prefix='/admin', tags=['Admin (demo)'])

    @router.post('/matches/export')
    async def export(body: SeedExport):
        schema, tables = await asyncio.to_thread(repository.export, body.match_id)
        return {'match_id': body.match_id, 'schema': schema, 'tables': tables}

    @router.post('/matches/restore')
    async def restore(body: SeedRestore):
        try:
            counts = await asyncio.to_thread(repository.restore, body.match_id, body.tables, body.max_seq,
                                             body.schema_)
        except SeedRefused as exc:
            raise RuleError('seed_refused', str(exc), 409) from exc
        await registry.adopt({'match_id': body.match_id, 'fixture': body.tables['received_matches'][0]['fixture']})
        return {'match_id': body.match_id, 'restored': counts}

    return router
