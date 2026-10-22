"""Received matches, canonical events and custom calculations (over SPADL actions) per matchId; tombstones and purge."""
from psycopg import sql
from psycopg.types.json import Jsonb

from backend.models.events import Event

# Match-scoped rows, children first: (table, column naming the match). Configuration
# (profiles, audience templates, prompts, backend_config) is never touched.
MATCH_TABLES = (
    ('subscription_clips', 'match_id=%s'),
    ('narrative_clips', 'match_id=%s'),
    ('subscription_narratives', 'match_id=%s'),
    ('subscriptions', 'match_id=%s'),
    ('subscription_topics', 'match_id=%s'),
    ('subscription_revisions', 'match_id=%s'),
    ('question_offers', 'conversation_id IN (SELECT id FROM question_conversations WHERE match_id=%s)'),
    ('question_turns', 'conversation_id IN (SELECT id FROM question_conversations WHERE match_id=%s)'),
    ('question_sessions', 'match_id=%s'),
    ('question_conversations', 'match_id=%s'),
    ('engine_narratives', 'match_id=%s'),
    ('audience_catalog', 'match_id=%s'),
    ('match_calculations', 'match_id=%s'),
    ('calculation_id_map', 'match_id=%s'),
    ('match_gaps', 'match_id=%s'),
    ('received_events', 'match_id=%s'),
    ('received_matches', 'match_id=%s'),
)



class MatchRepository:
    def __init__(self, store):
        self.store = store

    def accept_match(self, info):
        """Store an MA1 unless its match is tombstoned or it was sent before a purge-all cut-off.
        True when the match is (now) known."""
        with self.store.connect() as conn:
            if conn.execute('SELECT 1 FROM match_tombstones WHERE match_id=%s', (info.matchId,)).fetchone():
                return False
            cutoff = conn.execute('SELECT cutoff FROM match_purge_cutoff').fetchone()
            if cutoff and info.timeStamp < cutoff['cutoff']:
                return False
            conn.execute('INSERT INTO received_matches (match_id, fixture, source_match_id, run_id, provenance, sent_at) '
                         'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (info.matchId, info.fixture, info.sourceMatchId, info.runId, info.provenance, info.timeStamp))
            return True

    def matches(self):
        with self.store.connect() as conn:
            return conn.execute('SELECT match_id, fixture, source_match_id, run_id, provenance FROM received_matches '
                                'ORDER BY received_at').fetchall()

    def load(self, match_id):
        """Every received event in seq order, and the saved calculations."""
        with self.store.connect() as conn:
            events = [Event.model_validate(row['event']) for row in conn.execute(
                'SELECT event FROM received_events WHERE match_id=%s ORDER BY seq', (match_id,))]
            calculations = conn.execute('SELECT calculation_id, label, rule, result FROM match_calculations '
                                        'WHERE match_id=%s ORDER BY calculation_id', (match_id,)).fetchall()
        return events, calculations

    def append(self, match_id, events, results=(), gaps=()):
        """Commit consecutive (seq, event) pairs, the custom results they changed and any filled
        gaps (seq, state, blocked seconds) together."""
        with self.store.connect() as conn, conn.cursor() as cursor:
            cursor.executemany('INSERT INTO match_gaps (match_id, seq, state, blocked_seconds) VALUES (%s,%s,%s,%s)',
                               [(match_id, *gap) for gap in gaps])
            cursor.executemany('INSERT INTO received_events (match_id, seq, event) VALUES (%s,%s,%s)',
                               [(match_id, seq, Jsonb(event.model_dump(mode='json'))) for seq, event in events])
            cursor.executemany('UPDATE match_calculations SET result=%s WHERE match_id=%s AND calculation_id=%s',
                               [(Jsonb(result), match_id, result['calculation_id']) for result in results])

    def update_results(self, match_id, results):
        """The latest result (value and delivery version) of calculations changed by new SPADL actions."""
        with self.store.connect() as conn, conn.cursor() as cursor:
            cursor.executemany('UPDATE match_calculations SET result=%s WHERE match_id=%s AND calculation_id=%s',
                               [(Jsonb(result), match_id, result['calculation_id']) for result in results])

    def register(self, match_id, label, rule, result):
        with self.store.connect() as conn:
            conn.execute('INSERT INTO match_calculations (match_id, calculation_id, label, rule, result) '
                         'VALUES (%s,%s,%s,%s,%s) ON CONFLICT (match_id, calculation_id) DO NOTHING',
                         (match_id, result['calculation_id'], label, Jsonb(rule), Jsonb(result)))

    def gaps(self, limit=50):
        """The latest filled gaps across matches."""
        with self.store.connect() as conn:
            return conn.execute("SELECT match_id, seq, state, blocked_seconds, to_char(resolved_at AT TIME ZONE 'UTC', "
                                "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS resolved_at FROM match_gaps "
                                'ORDER BY resolved_at DESC LIMIT %s', (limit,)).fetchall()

    def checkpoints(self):
        with self.store.connect() as conn:
            return {row['partition_id']: row['sequence_number']
                    for row in conn.execute('SELECT partition_id, sequence_number FROM stream_checkpoints')}

    def checkpoint(self, partition_id, sequence_number):
        with self.store.connect() as conn:
            conn.execute('INSERT INTO stream_checkpoints (partition_id, sequence_number) VALUES (%s,%s) '
                     'ON CONFLICT (partition_id) DO UPDATE SET sequence_number=GREATEST('
                     'stream_checkpoints.sequence_number, EXCLUDED.sequence_number)', (partition_id, sequence_number))

    def reset_checkpoint(self, partition_id):
        """Forget a partition's position: its hub was recreated and numbers from 0 again."""
        with self.store.connect() as conn:
            conn.execute('DELETE FROM stream_checkpoints WHERE partition_id=%s', (partition_id,))

    def tombstoned(self, match_id):
        with self.store.connect() as conn:
            return conn.execute('SELECT 1 FROM match_tombstones WHERE match_id=%s', (match_id,)).fetchone() is not None

    def purge(self, match_id=None):
        """Tombstone first, then delete. `match_id=None` purges every known match and records a
        cut-off. Returns (purged match ids, rows deleted per table)."""
        counts = dict.fromkeys((table for table, _ in MATCH_TABLES), 0)
        with self.store.connect() as conn:
            if match_id is None:
                conn.execute('INSERT INTO match_purge_cutoff (cutoff) VALUES (now()) '
                             'ON CONFLICT (singleton) DO UPDATE SET cutoff=now()')
                ids = [row['match_id'] for row in conn.execute('SELECT match_id FROM received_matches')]
            else:
                ids = [match_id]
            for identifier in ids:
                conn.execute('INSERT INTO match_tombstones (match_id) VALUES (%s) ON CONFLICT DO NOTHING', (identifier,))
            for identifier in ids:
                # This match's viewers' follows of another match go with their conversations (cascade): that
                # match's engine re-reads its targets only on a new revision.
                conn.execute('''INSERT INTO subscription_revisions (match_id, revision)
                    SELECT DISTINCT s.match_id, 1 FROM subscriptions s
                    JOIN question_conversations c ON c.id = s.conversation_id
                    JOIN received_matches m ON m.match_id = s.match_id
                    WHERE c.match_id = %s AND s.match_id <> %s
                    ON CONFLICT (match_id) DO UPDATE SET revision = subscription_revisions.revision + 1''',
                             (identifier, identifier))
                for table, condition in MATCH_TABLES:
                    cursor = conn.execute(sql.SQL('DELETE FROM {} WHERE ').format(sql.Identifier(table))
                                          + sql.SQL(condition), (identifier,))
                    counts[table] += cursor.rowcount
        return ids, counts
