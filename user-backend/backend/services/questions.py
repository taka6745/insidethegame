"""Question use cases. Model work stays outside replay and database locks."""
import asyncio
import logging
from contextlib import asynccontextmanager
from backend.domain import RuleError
from backend.models.questions import QuestionDraft, QuestionReply
from backend.models.rules import Rule
from .question_tools import QuestionTools
from .question_answers import resolve_answer

class QuestionService:
    def __init__(self, repository, snapshots, match_data, narratives, agent, planner, *, timeout=60, max_active=4):
        if isinstance(max_active, bool) or not isinstance(max_active, int) or not 1 <= max_active <= 32:
            raise ValueError('QUESTION_MAX_ACTIVE must be an integer between 1 and 32')
        self.repository, self.snapshots, self.match_data, self.narratives = repository, snapshots, match_data, narratives
        self.agent, self.planner, self.timeout = agent, planner, timeout
        self._session_lock = asyncio.Lock()
        self.session_started = None
        # One application-wide service owns this admission limit, across profiles
        # and session takeovers. Replicas require a separate distributed budget.
        self._slots = asyncio.Semaphore(max_active)

    @asynccontextmanager
    async def session_guard(self):
        """Fence external session attachment against takeover in every API."""
        async with self._session_lock:
            yield

    async def initialize(self):
        await asyncio.to_thread(self.repository.initialize)

    async def profiles(self):
        return {'profiles':await asyncio.to_thread(self.repository.profiles),'mode':self.agent.mode}

    async def start(self, profile_id):
        async with self._session_lock:
            identity = await self.snapshots.identity()
            token = await asyncio.to_thread(self.repository.start, profile_id, identity)
            if self.session_started:
                self.session_started(profile_id)
            return await self.read(token)

    async def read(self, token):
        row = await asyncio.to_thread(self.repository.read, token)
        identity = await self.snapshots.identity()
        if row['run_id'] != identity.run_id:
            raise RuleError('run_changed','The match run changed. Open a new chat session.',409)
        return {**row,'mode':self.agent.mode,'synthetic':True}

    async def ask(self, token, request_id, prompt):
        # Fail fast rather than accumulating an unbounded queue of model work.
        # There is no yield between this check and an available semaphore acquire.
        if self._slots.locked():
            raise RuleError('question_capacity', 'The question service is busy. Please try again shortly.', 503)
        async with self._slots:
            return await self._ask(token, request_id, prompt)

    async def _ask(self, token, request_id, prompt):
        row = await self.read(token)
        payload = await self.snapshots.capture()
        if row['run_id'] != payload.snapshot.run_id:
            raise RuleError('run_changed','The match run changed.',409)
        turn = await asyncio.to_thread(self.repository.begin,token,request_id,prompt)
        if turn['status'] != 'pending':
            return turn['reply']
        # A retry of an in-flight request must not execute it twice.
        if not turn['created']:
            raise RuleError('question_busy','Please wait for the current answer.',409)
        try:
            async with asyncio.timeout(self.timeout):
                await asyncio.gather(self.match_data.capture(payload), self.narratives.capture(payload))
                stats, compact = await asyncio.gather(self.match_data.stats(payload.snapshot), self.narratives.compact(payload.snapshot))
                profile = next(p for p in await asyncio.to_thread(self.repository.profiles) if p['id'] == row['profile_id'])
                history = [{'user':t['prompt'],'reply':{key:t['reply'].get(key) for key in ('status','answer_kind','text','goal','statistic_request','standard_stat_id')}} for t in row['turns'][-12:] if t['reply']]
                toolkit = QuestionTools(payload,self.match_data,self.narratives,self.planner,stats['stats'],compact,history)
                context = {'snapshot':payload.snapshot.model_dump(), 'teams':payload.teams,'players':payload.players,
                    'data_reference':payload.data_reference,'profile':profile,'history':history,
                    'standard_stats':[{**s,'evidence_id':'stat:'+s['id']} for s in stats['stats']],
                    'compact':{**compact,'tail':[toolkit._event_reference(e) for e in compact.get('tail', [])[:100]],
                               'tail_truncated':len(compact.get('tail', [])) > 100,
                               'key_events':[toolkit._event_reference(e) for e in compact.get('key_events', [])[-100:]]}}
                draft = QuestionDraft.model_validate(await self.agent.answer(prompt,context,toolkit))
                draft = await resolve_answer(draft, toolkit)
                if any(identifier not in toolkit.evidence for identifier in draft.evidence_ids):
                    raise ValueError('Unverified evidence reference')
                offers = toolkit.offers if draft.status == 'answer' and not draft.standard_stat_id else []
                if offers:
                    # Numeric custom results always come from deterministic evaluation, never model prose.
                    draft.text = ' '.join(f"{o['label']}: {o['value']}." for o in offers)
                if draft.status == 'unsupported':
                    draft.text = 'Sorry, I cannot answer that from the information available.'
                reply = QuestionReply(**draft.model_dump(),snapshot=payload.snapshot,offers=offers,
                    evidence=[toolkit.evidence[i] for i in draft.evidence_ids],mode=self.agent.mode,goal=toolkit.goal if offers else None).model_dump(mode='json')
            async with self._session_lock:
                # Run cannot change between this check and the database commit.
                async with self.snapshots.run_guard(payload.snapshot.run_id):
                    await asyncio.to_thread(self.repository.finish,token,turn['id'],reply)
            return reply
        except BaseException as exc:
            try:
                await asyncio.shield(asyncio.to_thread(self.repository.fail,token,turn['id']))
            except RuleError:
                pass
            if isinstance(exc,(RuleError,asyncio.CancelledError)):
                raise
            logging.getLogger(__name__).warning('Question failed: %s',type(exc).__name__)
            return {'status':'unsupported','text':'Sorry, I could not answer that. Please try again.',
                    'snapshot':payload.snapshot.model_dump(),'mode':self.agent.mode,'offers':[],'evidence':[]}

    async def track(self, token, offer_id):
        async with self._session_lock:
            row = await self.read(token)
            offer = await asyncio.to_thread(self.repository.offer,token,offer_id)
            document = offer['document']
            if document['run_id'] != row['run_id']:
                raise RuleError('run_changed','This offer belongs to an earlier run.',409)
            calculation = await self.snapshots.track(row['run_id'],Rule.model_validate(document['rule']),document['label'])
            # Registration releases the replay lock. Fence the durable link too:
            # a reset in between must not mark an already deleted rule tracked.
            async with self.snapshots.run_guard(row['run_id']):
                await asyncio.to_thread(self.repository.tracked,token,offer_id,calculation['id'])
            return {'offer_id':str(offer_id),'calculation':calculation,'tracked':True}
