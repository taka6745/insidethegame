"""The narrative engine's live narratives per match; text is stored as delivered."""
from psycopg.types.json import Jsonb


class EngineNarratives:
    # Newest rows per snapshot read, across the match's buckets (about 92 minutes x 12 buckets fit, plus key moments).
    def __init__(self, store, limit=2400):
        self.store, self.limit = store, limit

    def save(self, narrative):
        """True if new; redeliveries (same id) and unknown or purged matches change nothing."""
        with self.store.connect() as conn:
            cursor = conn.execute('''INSERT INTO engine_narratives (id, match_id, bucket_id, seq, step_id,
                period, time_min, time_sec, clock_seconds, event_seq, text, trigger, prompt_version, tokens,
                audience_revision, created_at)
                SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                WHERE EXISTS (SELECT 1 FROM received_matches WHERE match_id=%s)
                ON CONFLICT (id) DO NOTHING''',
                (narrative.id, narrative.matchId, narrative.userType, narrative.seq, narrative.stepId,
                 narrative.matchTime.periodId, narrative.matchTime.timeMin, 59 if narrative.timeSec is None else narrative.timeSec,
                 narrative.clock_seconds, narrative.eventSeq, narrative.text, Jsonb(narrative.trigger.model_dump()),
                 narrative.promptVersion, Jsonb(narrative.tokens) if narrative.tokens else None,
                 narrative.audienceRevision, narrative.createdAt, narrative.matchId))
            return cursor.rowcount == 1

    def save_clip(self, clip):
        """A key event's clip for the shared narratives of its buckets (models.EngineMomentClip). True if any row is
        new; redeliveries and unknown or purged matches change nothing."""
        with self.store.connect() as conn, conn.cursor() as cursor:
            added = 0
            for bucket in dict.fromkeys(clip.buckets):
                cursor.execute('''INSERT INTO narrative_clips (match_id, bucket_id, moment_id, event_seq, step_id)
                    SELECT %s,%s,%s,%s,%s WHERE EXISTS (SELECT 1 FROM received_matches WHERE match_id=%s)
                    ON CONFLICT DO NOTHING''',
                               (clip.matchId, bucket, f'km:{clip.eventId}', clip.eventSeq, clip.stepId, clip.matchId))
                added += cursor.rowcount
            return added > 0

    def clips(self, snapshot, per_bucket):
        """{bucket_id: [moment_id, …]} of the match's key-event clips decided at or before the snapshot, oldest
        first, at most the newest `per_bucket` per bucket."""
        with self.store.connect() as conn:
            rows = conn.execute('''SELECT bucket_id, moment_id FROM (SELECT bucket_id, moment_id, event_seq,
                    row_number() OVER (PARTITION BY bucket_id ORDER BY event_seq DESC, moment_id DESC) AS newest
                FROM narrative_clips WHERE match_id=%s AND event_seq <= %s) c
                WHERE newest <= %s ORDER BY bucket_id, event_seq, moment_id''',
                                (snapshot.match_id, snapshot.seq, per_bucket)).fetchall()
        found = {}
        for r in rows:
            found.setdefault(r['bucket_id'], []).append(r['moment_id'])
        return found

    def items(self, snapshot, closed_through=0):
        """The match's newest narratives written from data at or before the snapshot, oldest first,
        in the product feed's item shape (one bucket per item). Without an eventSeq, the clock bounds it.
        closed_through: the last period whose end the snapshot has observed; its steps (e.g. a
        full-time summary stamped after the final event's clock) are all released."""
        with self.store.connect() as conn:
            rows = conn.execute('''SELECT * FROM engine_narratives WHERE match_id=%s
                AND (event_seq <= %s OR (event_seq IS NULL AND ((period, clock_seconds) <= (%s, %s) OR period <= %s)))
                ORDER BY period DESC, clock_seconds DESC, created_at DESC LIMIT %s''',
                (snapshot.match_id, snapshot.seq, snapshot.period or 1, snapshot.clock_seconds or 0, closed_through,
                 self.limit)).fetchall()
        return [{'id': r['id'], 'text': r['text'], 'clock_seconds': r['clock_seconds'], 'period': r['period'],
                 'buckets': [r['bucket_id']], 'synthetic': True,
                 'trigger': r['trigger']['type'], 'prompt_version': r['prompt_version'],
                 'audience_revision': r['audience_revision'], 'event_seq': r['event_seq']} for r in reversed(rows)]
