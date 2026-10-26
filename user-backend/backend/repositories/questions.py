"""Conversation/session/offer persistence per (viewer, profile, match). Never hold a transaction over model work."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from backend.domain import RuleError

class QuestionRepository:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        """A restarted process cannot finish another process's in-flight answers."""
        with self.store.connect() as conn:
            conn.execute("UPDATE question_turns SET status='failed',reply=%s WHERE status='pending'", (Jsonb({'status':'unsupported','text':'Sorry, that question was interrupted. Please ask again.','offers':[]}),))

    def profiles(self):
        return self.store.profiles()

    def start(self, profile_id, match_id, viewer_id=''):
        """A new token for (viewer, profile, match); the previous token of that viewer's pair stops working.
        Another browser (another viewer_id) gets its own conversation and never takes this one over."""
        profile = next((p for p in self.profiles() if p['id'] == profile_id), None)
        if profile is None:
            raise RuleError('profile_not_found', 'Choose a profile.', 404)
        token = uuid4()
        with self.store.connect() as conn:
            row = conn.execute('INSERT INTO question_conversations(id,viewer_id,profile_id,match_id) VALUES(%s,%s,%s,%s) '
                'ON CONFLICT(viewer_id,profile_id,match_id) DO UPDATE SET profile_id=EXCLUDED.profile_id RETURNING *',
                (uuid4(), viewer_id, profile_id, match_id)).fetchone()
            conn.execute('INSERT INTO question_sessions(viewer_id,profile_id,match_id,token,conversation_id) VALUES(%s,%s,%s,%s,%s) '
                         'ON CONFLICT(viewer_id,profile_id,match_id) DO UPDATE SET token=EXCLUDED.token,conversation_id=EXCLUDED.conversation_id',
                         (viewer_id,profile_id,match_id,token,row['id']))
            # A takeover invalidates the in-flight response and makes the new session usable.
            conn.execute("UPDATE question_turns SET status='failed',reply=%s WHERE conversation_id=%s AND status='pending'",
                         (Jsonb({'status':'unsupported','text':'Sorry, that question was interrupted by a new session.','offers':[]}),row['id']))
        return str(token)

    def _session(self, conn, token, *, lock=False):
        row = conn.execute('SELECT c.*,s.token FROM question_sessions s JOIN question_conversations c ON c.id=s.conversation_id '
                           'WHERE s.token=%s' + (' FOR UPDATE OF s,c' if lock else ''), (token,)).fetchone()
        if row is None:
            raise RuleError('session_replaced', 'Another tab took over. Reconnect to continue here.', 409)
        return row

    def read(self, token):
        with self.store.connect() as conn:
            row = self._session(conn, token)
            turns = conn.execute("SELECT id,request_id,prompt,status,reply,channel FROM question_turns WHERE conversation_id=%s AND status<>'cleared' ORDER BY id", (row['id'],)).fetchall()
            offers = conn.execute('SELECT id,document,calculation_id FROM question_offers WHERE conversation_id=%s', (row['id'],)).fetchall()
        # Question and follow-chat turns share the table; each channel is its own conversation.
        channel = lambda name: [{k: t[k] for k in t if k != 'channel'} for t in turns
                                if t['channel'] == name]
        return {'session_token': str(token), 'profile_id':row['profile_id'], 'viewer_id': row['viewer_id'],
                'match_id':row['match_id'], 'audience': row['audience'], 'turns':channel('questions'),
                'follow_turns': channel('follow'),
                'offers':[{**r['document'],'id':str(r['id']),'calculation_id':r['calculation_id']} for r in offers]}

    def clear(self, token):
        """Reset Ask context while preserving tracked offers and the separate follow conversation."""
        with self.store.connect() as conn:
            row = self._session(conn, token, lock=True)
            if conn.execute("SELECT 1 FROM question_turns WHERE conversation_id=%s AND channel='questions' "
                            "AND status='pending'", (row['id'],)).fetchone():
                raise RuleError('question_busy', 'Please wait for the current answer before clearing Ask.', 409)
            conn.execute("DELETE FROM question_offers WHERE conversation_id=%s AND calculation_id IS NULL "
                         "AND turn_id IN (SELECT id FROM question_turns WHERE conversation_id=%s AND channel='questions')",
                         (row['id'], row['id']))
            conn.execute("UPDATE question_turns SET status='cleared', prompt='', reply=NULL "
                         "WHERE conversation_id=%s AND channel='questions'", (row['id'],))

    def set_audience(self, token, audience):
        with self.store.connect() as conn:
            row = self._session(conn, token, lock=True)
            conn.execute('UPDATE question_conversations SET audience=%s WHERE id=%s',
                         (Jsonb(audience), row['id']))

    def begin(self, token, request_id, prompt, channel='questions', per_minute=None):
        """A pending turn; `per_minute` caps the channel's turns in the last 60 s (429)."""
        with self.store.connect() as conn:
            row = self._session(conn, token, lock=True)
            existing = conn.execute('SELECT * FROM question_turns WHERE conversation_id=%s AND request_id=%s', (row['id'],request_id)).fetchone()
            if existing:
                if existing['prompt'] != prompt or existing['channel'] != channel:
                    raise RuleError('request_conflict','This request ID was already used for another question.',409)
                return {**existing, 'created':False}
            if conn.execute("SELECT 1 FROM question_turns WHERE conversation_id=%s AND channel=%s AND status='pending'", (row['id'],channel)).fetchone():
                raise RuleError('question_busy','Please wait for the current answer.',409)
            if per_minute is not None and conn.execute(
                    "SELECT count(*) AS n FROM question_turns WHERE conversation_id=%s AND channel=%s "
                    "AND created_at > now() - interval '60 seconds'", (row['id'], channel)).fetchone()['n'] >= per_minute:
                raise RuleError('rate_limited', 'Too many messages. Please wait a moment.', 429)
            created = conn.execute("INSERT INTO question_turns(conversation_id,request_id,prompt,status,channel) VALUES(%s,%s,%s,'pending',%s) RETURNING *",
                (row['id'],request_id,prompt,channel)).fetchone()
            return {**created, 'created':True}

    def finish(self, token, turn_id, reply):
        with self.store.connect() as conn:
            row = self._session(conn, token, lock=True)
            turn = conn.execute("UPDATE question_turns SET status='complete',reply=%s WHERE id=%s AND conversation_id=%s AND status='pending' RETURNING id",
                (Jsonb(reply),turn_id,row['id'])).fetchone()
            if not turn:
                raise RuleError('question_interrupted','This question is no longer active.',409)
            for offer in [*reply.get('offers',[]), *(o for part in reply.get('parts') or [] for o in part.get('offers',[]))]:
                conn.execute('INSERT INTO question_offers(id,conversation_id,turn_id,document) VALUES(%s,%s,%s,%s)',
                             (offer['id'],row['id'],turn_id,Jsonb(offer)))

    def fail(self, token, turn_id, reply=None):
        with self.store.connect() as conn:
            row = self._session(conn,token,lock=True)
            conn.execute("UPDATE question_turns SET status='failed',reply=%s WHERE id=%s AND conversation_id=%s AND status='pending'",
                         (Jsonb(reply or {'status':'unsupported','text':'Sorry, I could not answer that. Please try again.','offers':[]}),turn_id,row['id']))

    def offer(self, token, offer_id):
        with self.store.connect() as conn:
            row = self._session(conn,token)
            offer = conn.execute('SELECT * FROM question_offers WHERE id=%s AND conversation_id=%s',(offer_id,row['id'])).fetchone()
        if not offer:
            raise RuleError('offer_not_found','This stat offer is not in your conversation.',404)
        return offer

    def tracked(self,token,offer_id,calculation_id):
        with self.store.connect() as conn:
            row = self._session(conn,token,lock=True)
            conn.execute('UPDATE question_offers SET calculation_id=%s WHERE id=%s AND conversation_id=%s',
                         (calculation_id,offer_id,row['id']))

    def untrack(self, token, calculation_id):
        with self.store.connect() as conn:
            row = self._session(conn, token, lock=True)
            conn.execute('UPDATE question_offers SET calculation_id=NULL WHERE conversation_id=%s AND calculation_id=%s',
                         (row['id'], calculation_id))
