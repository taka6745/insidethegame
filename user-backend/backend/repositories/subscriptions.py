"""Story follows per match: topics, subscriptions (one active per viewer), revisions and delivered narratives."""
from uuid import uuid4

from psycopg.types.json import Jsonb

from backend.domain import RuleError

SESSION = ('SELECT c.id, c.match_id, c.audience FROM question_sessions s '
           'JOIN question_conversations c ON c.id = s.conversation_id WHERE s.token = %s FOR UPDATE OF c')
COLUMNS = 'id, match_id, topic_id, spec, since_seq, bucket_id, created_at, ended_at'


def _row(row):
    return row and {'subscription_id': str(row['id']), 'match_id': row['match_id'], 'topic_id': row['topic_id'],
                    'spec': row['spec'], 'bucket_id': row['bucket_id'],
                    'label': row['spec']['label'], 'since_seq': row['since_seq'],
                    'created_at': row['created_at'].isoformat(),
                    'ended_at': row['ended_at'] and row['ended_at'].isoformat()}


class SubscriptionRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _session(conn, token):
        row = conn.execute(SESSION, (token,)).fetchone()
        if row is None:
            raise RuleError('session_replaced', 'Another tab took over. Reconnect to continue here.', 409)
        return row

    @staticmethod
    def _bump(conn, match_id):
        conn.execute('INSERT INTO subscription_revisions (match_id, revision) SELECT %s, 1 '
                     'WHERE EXISTS (SELECT 1 FROM received_matches WHERE match_id=%s) '
                     'ON CONFLICT (match_id) DO UPDATE SET revision = subscription_revisions.revision + 1',
                     (match_id, match_id))

    @staticmethod
    def _limit(conn, conversation_id, per_minute):
        changes = conn.execute("SELECT count(*) FILTER (WHERE created_at > now() - interval '60 seconds') "
                               "+ count(*) FILTER (WHERE ended_at > now() - interval '60 seconds') AS n "
                               'FROM subscriptions WHERE conversation_id=%s', (conversation_id,)).fetchone()['n']
        if changes >= per_minute:
            raise RuleError('rate_limited', 'Too many follow changes. Please wait a moment.', 429)

    def listing(self, token):
        """(active follow or None, every follow of this viewer, newest first)."""
        with self.store.connect() as conn:
            session = self._session(conn, token)
            rows = conn.execute(f'SELECT {COLUMNS} FROM subscriptions WHERE conversation_id=%s ORDER BY created_at DESC',
                                (session['id'],)).fetchall()
        return next((_row(r) for r in rows if r['ended_at'] is None), None), [_row(r) for r in rows]

    def active(self, token):
        return self.listing(token)[0]

    def follow(self, token, match_id, spec, topic_id, seq, audience, per_minute, bucket_id=None):
        """(follow, created). Following the active topic again returns it; another active follow is 409.
        `match_id` is the followed match (another live match for a cross-match follow, written for
        `bucket_id` of that match's catalogue); the viewer's session may belong to another."""
        with self.store.connect() as conn:
            session = self._session(conn, token)
            current = conn.execute(f'SELECT {COLUMNS} FROM subscriptions WHERE conversation_id=%s AND ended_at IS NULL',
                                   (session['id'],)).fetchone()
            if current is not None:
                if current['topic_id'] == topic_id:
                    return _row(current), False
                raise RuleError('follow_limit', 'You already follow a story. Stop following it to choose another.', 409)
            self._limit(conn, session['id'], per_minute)
            if session['audience'] is None and audience:
                # The topic's buckets come from followers' saved audiences.
                conn.execute('UPDATE question_conversations SET audience=%s WHERE id=%s', (Jsonb(audience), session['id']))
            conn.execute('INSERT INTO subscription_topics (match_id, topic_id, spec, created_seq) '
                         'SELECT %s, %s, %s, %s WHERE EXISTS (SELECT 1 FROM received_matches WHERE match_id=%s) '
                         'ON CONFLICT DO NOTHING', (match_id, topic_id, Jsonb(spec), seq, match_id))
            # No topic (the match was purged meanwhile): no follow.
            row = conn.execute(f'INSERT INTO subscriptions (id, match_id, conversation_id, topic_id, spec, since_seq, '
                               f'bucket_id) SELECT %s, %s, %s, %s, %s, %s, %s FROM subscription_topics '
                               f'WHERE match_id=%s AND topic_id=%s RETURNING {COLUMNS}',
                               (uuid4(), match_id, session['id'], topic_id, Jsonb(spec), seq, bucket_id,
                                match_id, topic_id)).fetchone()
            if row is None:
                raise RuleError('match_not_found', 'That match is no longer available.', 404)
            self._bump(conn, match_id)
            return _row(row), True

    def unfollow(self, token, subscription_id, per_minute):
        with self.store.connect() as conn:
            session = self._session(conn, token)
            self._limit(conn, session['id'], per_minute)
            row = conn.execute(f'UPDATE subscriptions SET ended_at=now() WHERE id=%s AND conversation_id=%s '
                               f'AND ended_at IS NULL RETURNING {COLUMNS}', (subscription_id, session['id'])).fetchone()
            if row is None:
                raise RuleError('follow_not_found', 'You do not follow this story.', 404)
            self._bump(conn, row['match_id'])  # the followed match's targets change
            return _row(row)

    def audience_changed(self, token):
        """A follower moved bucket: the engine's targets change."""
        with self.store.connect() as conn:
            session = self._session(conn, token)
            row = conn.execute('SELECT match_id FROM subscriptions WHERE conversation_id=%s AND ended_at IS NULL '
                               'AND bucket_id IS NULL', (session['id'],)).fetchone()
            if row:  # a cross-match follow keeps its own bucket
                self._bump(conn, row['match_id'])

    def targets(self, match_id, limit):
        """(revision, topics with active followers, most followed first): spec, created_seq, followers, buckets."""
        with self.store.connect() as conn:
            revision = conn.execute('SELECT revision FROM subscription_revisions WHERE match_id=%s',
                                    (match_id,)).fetchone()
            rows = conn.execute('''SELECT t.topic_id, t.spec, t.created_seq, count(*) AS followers,
                    array_agg(DISTINCT COALESCE(s.bucket_id, c.audience->>'bucket_id'))
                        FILTER (WHERE COALESCE(s.bucket_id, c.audience->>'bucket_id') IS NOT NULL) AS buckets
                FROM subscriptions s JOIN subscription_topics t USING (match_id, topic_id)
                JOIN question_conversations c ON c.id = s.conversation_id
                WHERE s.match_id=%s AND s.ended_at IS NULL
                GROUP BY t.topic_id, t.spec, t.created_seq ORDER BY count(*) DESC, t.topic_id LIMIT %s''',
                                (match_id, limit)).fetchall()
        return (revision['revision'] if revision else 0), rows

    def save_narrative(self, n):
        """True if new; redeliveries and narratives of unknown or purged topics change nothing."""
        with self.store.connect() as conn:
            cursor = conn.execute('''INSERT INTO subscription_narratives (id, match_id, topic_id, bucket_id, seq, step_id,
                period, time_min, time_sec, clock_seconds, event_seq, text, trigger, decision, storyline_ids,
                prompt_version, tokens, created_at)
                SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                WHERE EXISTS (SELECT 1 FROM subscription_topics WHERE match_id=%s AND topic_id=%s)
                ON CONFLICT (id) DO NOTHING''',
                (n.id, n.matchId, n.topicId, n.userType, n.seq, n.stepId, n.matchTime.periodId, n.matchTime.timeMin,
                 59 if n.timeSec is None else n.timeSec, n.clock_seconds, n.eventSeq, n.text,
                 Jsonb(n.trigger.model_dump()), Jsonb(n.decision) if n.decision else None, Jsonb(n.storylineIds),
                 n.promptVersion, Jsonb(n.tokens) if n.tokens else None, n.createdAt, n.matchId, n.topicId))
            return cursor.rowcount == 1

    def save_clip(self, clip):
        """A moment Decision-1 judged worth a clip for a topic joins its playlist (models.EngineFollowClip). True if
        new; redeliveries and clips of unknown or purged topics change nothing."""
        with self.store.connect() as conn:
            return conn.execute('''INSERT INTO subscription_clips (match_id, topic_id, moment_id, event_seq, step_id)
                SELECT %s, %s, %s, %s, %s WHERE EXISTS (SELECT 1 FROM subscription_topics WHERE match_id=%s AND topic_id=%s)
                ON CONFLICT DO NOTHING''', (clip.matchId, clip.topicId, f'km:{clip.eventId}', clip.eventSeq, clip.stepId,
                                              clip.matchId, clip.topicId)).rowcount == 1

    def clips(self, snapshot, per_topic):
        """{topic_id: [moment_id, …]} of the match's follow clips written from data at or before the snapshot,
        oldest first, at most the newest `per_topic` per topic."""
        with self.store.connect() as conn:
            rows = conn.execute('''SELECT topic_id, moment_id FROM (SELECT topic_id, moment_id, event_seq,
                    row_number() OVER (PARTITION BY topic_id ORDER BY event_seq DESC, moment_id DESC) AS newest
                FROM subscription_clips WHERE match_id=%s AND event_seq <= %s) c
                WHERE newest <= %s ORDER BY topic_id, event_seq, moment_id''',
                                (snapshot.match_id, snapshot.seq, per_topic)).fetchall()
        found = {}
        for r in rows:
            found.setdefault(r['topic_id'], []).append(r['moment_id'])
        return found

    def narratives(self, snapshot, closed_through=0, limit=2400):
        """The match's follow narratives written from data at or before the snapshot (same bound as
        EngineNarratives.items), oldest first, in the feed's item shape plus `topic_id`."""
        with self.store.connect() as conn:
            rows = conn.execute('''SELECT * FROM subscription_narratives WHERE match_id=%s
                AND (event_seq <= %s OR (event_seq IS NULL AND ((period, clock_seconds) <= (%s, %s) OR period <= %s)))
                ORDER BY period DESC, clock_seconds DESC, created_at DESC LIMIT %s''',
                (snapshot.match_id, snapshot.seq, snapshot.period or 1, snapshot.clock_seconds or 0, closed_through,
                 limit)).fetchall()
        return [{'id': r['id'], 'kind': 'subscription', 'topic_id': r['topic_id'], 'text': r['text'],
                 'clock_seconds': r['clock_seconds'], 'period': r['period'], 'buckets': [r['bucket_id']],
                 'synthetic': True, 'trigger': r['trigger']['type'], 'prompt_version': r['prompt_version'],
                 'event_seq': r['event_seq'], 'storyline_ids': r['storyline_ids']} for r in reversed(rows)]
