"""Conversation/session/offer persistence. Never hold a transaction over model work."""
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from backend.domain import RuleError

class QuestionRepository:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.connect() as conn:
            conn.execute((Path(__file__).parents[2] / 'migrations/006_questions.sql').read_text())
            conn.execute("UPDATE question_turns SET status='failed',reply=%s WHERE status='pending'", (Jsonb({'status':'unsupported','text':'Sorry, that question was interrupted. Please ask again.','offers':[]}),))

    def profiles(self):
        return self.store.profiles()

    def start(self, profile_id, snapshot):
        profile = next((p for p in self.profiles() if p['id'] == profile_id), None)
        if profile is None:
            raise RuleError('profile_not_found', 'Choose a demo profile.', 404)
        token = uuid4()
        with self.store.connect() as conn:
            row = conn.execute('INSERT INTO question_conversations(id,profile_id,run_id,match_id) VALUES(%s,%s,%s,%s) '
                'ON CONFLICT(profile_id,run_id) DO UPDATE SET match_id=EXCLUDED.match_id RETURNING *',
                (uuid4(), profile_id, snapshot.run_id, snapshot.match_id)).fetchone()
            conn.execute('INSERT INTO question_sessions(profile_id,token,conversation_id) VALUES(%s,%s,%s) '
                         'ON CONFLICT(profile_id) DO UPDATE SET token=EXCLUDED.token,conversation_id=EXCLUDED.conversation_id',
                         (profile_id,token,row['id']))
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
            turns = conn.execute('SELECT id,request_id,prompt,status,reply FROM question_turns WHERE conversation_id=%s ORDER BY id', (row['id'],)).fetchall()
            offers = conn.execute('SELECT id,document,calculation_id FROM question_offers WHERE conversation_id=%s', (row['id'],)).fetchall()
        return {'session_token': str(token), 'profile_id':row['profile_id'], 'run_id':row['run_id'],
                'match_id':row['match_id'], 'turns':turns,
                'offers':[{**r['document'],'id':str(r['id']),'calculation_id':r['calculation_id']} for r in offers]}

    def begin(self, token, request_id, prompt):
        with self.store.connect() as conn:
            row = self._session(conn, token, lock=True)
            existing = conn.execute('SELECT * FROM question_turns WHERE conversation_id=%s AND request_id=%s', (row['id'],request_id)).fetchone()
            if existing:
                if existing['prompt'] != prompt:
                    raise RuleError('request_conflict','This request ID was already used for another question.',409)
                return {**existing, 'created':False}
            if conn.execute("SELECT 1 FROM question_turns WHERE conversation_id=%s AND status='pending'", (row['id'],)).fetchone():
                raise RuleError('question_busy','Please wait for the current answer.',409)
            created = conn.execute("INSERT INTO question_turns(conversation_id,request_id,prompt,status) VALUES(%s,%s,%s,'pending') RETURNING *",
                (row['id'],request_id,prompt)).fetchone()
            return {**created, 'created':True}

    def finish(self, token, turn_id, reply):
        with self.store.connect() as conn:
            row = self._session(conn, token, lock=True)
            turn = conn.execute("UPDATE question_turns SET status='complete',reply=%s WHERE id=%s AND conversation_id=%s AND status='pending' RETURNING id",
                (Jsonb(reply),turn_id,row['id'])).fetchone()
            if not turn:
                raise RuleError('question_interrupted','This question is no longer active.',409)
            for offer in reply.get('offers',[]):
                conn.execute('INSERT INTO question_offers(id,conversation_id,turn_id,document) VALUES(%s,%s,%s,%s)',
                             (offer['id'],row['id'],turn_id,Jsonb(offer)))

    def fail(self, token, turn_id):
        with self.store.connect() as conn:
            row = self._session(conn,token,lock=True)
            conn.execute("UPDATE question_turns SET status='failed',reply=%s WHERE id=%s AND conversation_id=%s AND status='pending'",
                         (Jsonb({'status':'unsupported','text':'Sorry, I could not answer that. Please try again.','offers':[]}),turn_id,row['id']))

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
