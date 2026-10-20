"""Question use cases. Model work stays outside replay and database locks."""
import asyncio
import time
import logging
from contextlib import asynccontextmanager
from backend.domain import RuleError
from backend.models.questions import QuestionDraft, QuestionReply
from backend.models.rules import Rule
from backend.models.stat_offers import pin_id, stat_answer
from .question_tools import QuestionTools
from .question_answers import UNAVAILABLE, model_catalogue, resolve_answer
from backend.adapters.usage import as_dict as usage_dict, start_usage
from .replay import ReplayBuilder, ReplayTools
from .replay_clips import MAX_ITEMS

class QuestionService:
    def __init__(self, repository, snapshots, match_data, narratives, agent, planner, *, timeout=60, max_active=4,
                 replays=None):
        if isinstance(max_active, bool) or not isinstance(max_active, int) or not 1 <= max_active <= 32:
            raise ValueError('QUESTION_MAX_ACTIVE must be an integer between 1 and 32')
        self.repository, self.snapshots, self.match_data, self.narratives = repository, snapshots, match_data, narratives
        self.agent, self.planner, self.timeout = agent, planner, timeout
        self.replays = replays or ReplayBuilder()
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
                await self.session_started(profile_id)
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

    async def _capture(self):
        return await self.pin(await self.snapshots.capture())

    async def pin(self, payload):
        """Pin a live snapshot back to the newest one both upstreams have observed."""
        observed = getattr(self.narratives, 'observed_cursor', None)
        cursor = await observed(payload.snapshot) if observed else None
        if cursor is not None and cursor < payload.snapshot.cursor:
            payload = await self.snapshots.capture(cursor)
        return payload

    async def _ask(self, token, request_id, prompt):
        row = await self.read(token)
        payload = await self._capture()
        if row['run_id'] != payload.snapshot.run_id:
            raise RuleError('run_changed','The match run changed.',409)
        turn = await asyncio.to_thread(self.repository.begin,token,request_id,prompt)
        if turn['status'] != 'pending':
            return turn['reply']
        # A retry of an in-flight request must not execute it twice.
        if not turn['created']:
            raise RuleError('question_busy','Please wait for the current answer.',409)
        started, usage = time.perf_counter(), start_usage()
        try:
            async with asyncio.timeout(self.timeout):
                await self.match_data.capture(payload)
                await self.narratives.capture(payload)
                stats, compact = await asyncio.gather(self.match_data.stats(payload.snapshot), self.narratives.compact(payload.snapshot))
                profile = next(p for p in await asyncio.to_thread(self.repository.profiles) if p['id'] == row['profile_id'])
                profile = {**profile, **(row.get('audience') or {})}
                # Demo account labels may name a different team/style than this match choice.
                profile = {key: profile[key] for key in ('team', 'fan_style')}
                history = [{'user':t['prompt'],'reply':{key:t['reply'].get(key) for key in ('status','answer_kind','text','clarification','goal','statistic_request','standard_stat_id')}} for t in row['turns'][-12:] if t['reply']]
                toolkit = QuestionTools(payload,self.match_data,self.narratives,self.planner,stats['stats'],compact,history)
                context = {'snapshot':payload.snapshot.model_dump(), 'teams':payload.teams,'players':payload.players,
                    'data_reference':payload.data_reference,'profile':profile,'history':history,
                    'standard_stats':[{**s,'evidence_id':'stat:'+s['id']} for s in model_catalogue(stats['stats'])],
                    'compact':{**compact,'tail':[toolkit._event_reference(e) for e in compact.get('tail', [])[:100]],
                               'tail_truncated':len(compact.get('tail', [])) > 100,
                               'key_events':[toolkit._event_reference(e) for e in compact.get('key_events', [])[-100:]]}}
                draft = QuestionDraft.model_validate(await self.agent.answer(prompt,context,toolkit))
                draft = await resolve_answer(draft, toolkit)
                if any(identifier not in toolkit.evidence for identifier in draft.evidence_ids):
                    raise ValueError('Unverified evidence reference')
                offers = toolkit.offers if draft.status == 'answer' else []
                if offers:
                    # Stat values come from ETL or deterministic evaluation, never model prose.
                    draft.text = ' '.join(stat_answer(offer) for offer in offers)
                if draft.status == 'unsupported' and draft.answer_kind == 'replay':
                    # Statistic and routing refusals carry checked fixed reasons; replay prose does not.
                    draft.text = UNAVAILABLE
                replay = None
                if draft.answer_kind == 'replay' and draft.status == 'answer' and draft.replay_items:
                    items = [item.model_dump() for item in draft.replay_items]
                    await toolkit.replay.load()  # Summary plans may cite only key moments.
                    replay = {**self.replays.build(toolkit.replay, items), 'items': items,
                              'refine_offer': draft.refine_offer, 'derived': toolkit.replay.derived}
                reply = QuestionReply(**draft.model_dump(),snapshot=payload.snapshot,offers=offers,
                    evidence=[toolkit.evidence[i] for i in draft.evidence_ids],mode=self.agent.mode,goal=toolkit.goal if offers else None,
                    replay=replay, usage=usage_dict(usage, time.perf_counter() - started)).model_dump(mode='json')
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
            # Validation messages name IDs and steps, never credentials; other errors log their type only.
            detail = str(exc)[:300] if isinstance(exc, ValueError) else ''
            logging.getLogger(__name__).warning('Question %s failed: %s %s', turn['id'], type(exc).__name__, detail)
            return {'status':'unsupported','text':'Sorry, I could not answer that. Please try again.',
                    'snapshot':payload.snapshot.model_dump(),'mode':self.agent.mode,'offers':[],'evidence':[]}

    async def replay_page(self, token, turn_id, page):
        """Another page of a saved replay, re-cut against a fresh observed snapshot. No model call."""
        row = await self.read(token)
        turn = next((t for t in row['turns'] if t['id'] == turn_id and t['reply']), None)
        saved = turn and turn['reply'].get('replay')
        if not saved or not 0 <= page < saved.get('page_count', MAX_ITEMS):
            raise RuleError('replay_not_found', 'That replay page is not available.', 404)
        payload = await self._capture()
        if payload.snapshot.run_id != row['run_id']:
            raise RuleError('run_changed', 'The match run changed.', 409)
        await self.match_data.capture(payload)
        await self.narratives.capture(payload)
        tools = ReplayTools(payload.snapshot, self.match_data, self.narratives, payload.players, payload.teams)
        await tools.load()
        if any(item['kind'] == 'key_moment' for item in saved['items']):
            await tools.key_moments()
        tools.cited |= {item['source_id'] for item in saved['items'] if item['kind'] == 'event' and item['source_id'] in tools.events}
        return {**self.replays.build(tools, saved['items'], page, until=saved.get('observed_until')), 'items': saved['items'],
                'refine_offer': saved.get('refine_offer'), 'derived': saved.get('derived')}

    async def track(self, token, offer_id):
        async with self._session_lock:
            row = await self.read(token)
            offer = await asyncio.to_thread(self.repository.offer,token,offer_id)
            document = offer['document']
            if document['run_id'] != row['run_id']:
                raise RuleError('run_changed','This offer belongs to an earlier run.',409)
            if document.get('kind') == 'standard':
                payload = await self._capture()
                if payload.snapshot.run_id != row['run_id']:
                    raise RuleError('run_changed', 'This offer belongs to an earlier run.', 409)
                await self.match_data.capture(payload)
                stats = await self.match_data.stats(payload.snapshot)
                stat = next((s for s in stats['stats'] if s['id'] == document['standard_stat_id']), None)
                if not stat or not stat.get('available') or not stat.get('complete'):
                    raise RuleError('stat_unavailable', 'This statistic is temporarily unavailable.', 503)
                calculation = {**stat, 'id': pin_id(document), 'kind': 'standard',
                               'standard_stat_id': stat['id']}
            else:
                calculation = await self.snapshots.track(row['run_id'],Rule.model_validate(document['rule']),document['label'])
            # Registration releases the replay lock. Fence the durable link too:
            # a reset in between must not mark an already deleted rule tracked.
            async with self.snapshots.run_guard(row['run_id']):
                await asyncio.to_thread(self.repository.tracked,token,offer_id,calculation['id'])
            return {'offer_id':str(offer_id),'calculation':calculation,'tracked':True}
