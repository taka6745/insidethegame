"""Question use cases per (profile, match). Model work stays outside match and database locks."""
import asyncio
import logging
import time
from contextlib import asynccontextmanager

import httpx

from backend.adapters.decision import Window, state as decision_state
from backend.adapters.usage import as_dict as usage_dict, start_usage
from backend.domain import RuleError
from backend.models.questions import QuestionDraft, QuestionReply
from backend.models.rules import Rule
from backend.models.stat_offers import pin_id, stat_answer, viewer_pin_id
from backend.services.cross_match import header
from backend.services.question_answers import UNAVAILABLE, model_catalogue, resolve_answer
from backend.services.question_tools import QuestionTools
from backend.services.locks import KeyedLocks
from backend.services.replay import ReplayBuilder, ReplayTools

NO_MODEL = 'Questions are unavailable: no model is configured for this service.'
# ETL trend windows (etl/contracts output 4) in words, for evidence labels.
WINDOWS = {'last5': 'last 5 minutes', 'prev10': 'the 10 minutes before the last 5', 'last15': 'last 15 minutes',
           'half': 'this half', 'match': 'whole match'}


class QuestionService:
    def __init__(self, repository, registry, match_data, narratives, agent, planner, config, *, timeout=240,
                 max_active=4, replays=None, cross=None, decide=None):
        if isinstance(max_active, bool) or not isinstance(max_active, int) or not 1 <= max_active <= 32:
            raise ValueError('QUESTION_MAX_ACTIVE must be an integer between 1 and 32')
        self.repository, self.registry, self.match_data, self.narratives = repository, registry, match_data, narratives
        self.agent, self.planner, self.config, self.timeout = agent, planner, config, timeout
        self.replays = replays or ReplayBuilder()
        self.cross = cross  # services/cross_match.CrossMatch: questions and pins about the other live matches
        self.decide, self._offers = decide, Window()  # adapters/decision: "Follow this story?" offers
        self._locks = KeyedLocks()  # Session takeover fencing, per match.
        self.session_started = None  # async callback(match_id, profile_id, viewer_id): a takeover closes that viewer's old socket.
        # One application-wide admission limit, across matches, profiles and takeovers.
        self._slots = asyncio.Semaphore(max_active)

    @property
    def mode(self):
        return self.agent.mode if self.agent else 'unavailable'

    @asynccontextmanager
    async def session_guard(self, match_id):
        """Fence external session attachment against takeover of this match's sessions."""
        async with self._locks(match_id):
            yield

    async def initialize(self):
        await asyncio.to_thread(self.repository.initialize)

    async def profiles(self):
        return {'profiles': await asyncio.to_thread(self.repository.profiles), 'mode': self.mode}

    async def profile(self, profile_id):
        """A session's demo account; it may have been removed in the profile editor since."""
        profile = next((p for p in await asyncio.to_thread(self.repository.profiles) if p['id'] == profile_id), None)
        if profile is None:
            raise RuleError('profile_not_found', 'That profile was removed. Choose another.', 409)
        return profile

    async def start(self, match_id, profile_id, viewer_id=''):
        async with self._locks(match_id):
            await self.registry.require(match_id)
            token = await asyncio.to_thread(self.repository.start, profile_id, match_id, viewer_id)
            if self.session_started:
                await self.session_started(match_id, profile_id, viewer_id)
            return await self.read(match_id, token)

    async def read(self, match_id, token):
        """A token belongs to one match: under another match id it is unknown."""
        self.registry.get(match_id)  # An unknown or purged match is 404 before any session check.
        row = await asyncio.to_thread(self.repository.read, token)
        if row['match_id'] != match_id:
            raise RuleError('session_not_found', 'This session belongs to another match.', 404)
        return {**row, 'mode': self.mode, 'synthetic': True}

    async def ask(self, match_id, token, request_id, prompt, seq=None):
        """`seq`: the snapshot the viewer's picture shows; the answer never cites anything later."""
        if self.agent is None:
            raise RuleError('model_unavailable', NO_MODEL, 503)
        # Fail fast rather than accumulating an unbounded queue of model work.
        # There is no yield between this check and an available semaphore acquire.
        if self._slots.locked():
            raise RuleError('question_capacity', 'The question service is busy. Please try again shortly.', 503)
        async with self._slots:
            return await self._ask(match_id, token, request_id, prompt, seq)

    async def _ask(self, match_id, token, request_id, prompt, seq):
        row = await self.read(match_id, token)
        here = match = self.registry.get(match_id)
        # A question naming another live match is answered from that match at its own position, never this seq.
        other = self.cross and await self.cross.named(here, prompt)
        info = None
        if other:
            match, info = other
            payload = await self.match_data.capture(match)
        else:
            payload = await self.match_data.capture(match, seq)
        turn = await asyncio.to_thread(self.repository.begin, token, request_id, prompt)
        if turn['status'] != 'pending':
            return turn['reply']
        # A retry of an in-flight request must not execute it twice.
        if not turn['created']:
            raise RuleError('question_busy', 'Please wait for the current answer.', 409)
        started, usage = time.perf_counter(), start_usage()
        try:
            async with asyncio.timeout(self.timeout):
                reply, draft, offers = await self._answer(prompt, row, here, match, info, payload, usage, started)
                if draft.per_match and self.cross:
                    # A request about several live matches: one answer from each, at each one's own position.
                    async def part_of(part_id):
                        part_match, part_info = here, None
                        if part_id != here.match_id:
                            part_match = await self.cross.other(here.match_id, part_id)
                            part_info = await self.cross.info_of(part_match)
                            if part_info is None:
                                return None  # unmarked, it would read as this match's answer
                        part_payload = await self.match_data.capture(part_match, seq if part_match is here else None)
                        part, _, _ = await self._answer(prompt, row, here, part_match, part_info, part_payload, usage,
                                                        started, single=True)
                        return {**part, 'usage': None}  # the whole answer's usage is receipted once, below
                    # Every match at once (each part is its own agent run): the parts keep the asked order.
                    parts = [part for part in await asyncio.gather(*map(part_of, draft.per_match)) if part]
                    # The parts carry their own match headers; the answer as a whole belongs to no one match.
                    reply = {**reply, 'parts': parts, 'other_match': None,
                             'usage': usage_dict(usage, time.perf_counter() - started)}
                    offers = []
            # Outside the answer's timeout: a slow offer check (its own timeout) never fails the answer.
            reply['follow_offer'] = None if reply.get('parts') else await self._follow_offer(
                prompt, draft, offers, reply['other_match'])
            async with self._locks(match_id), here.guard():
                # The match cannot be purged between this check and the database commit.
                await asyncio.to_thread(self.repository.finish, token, turn['id'], reply)
            return reply
        except BaseException as exc:
            failure = None
            if not isinstance(exc, (RuleError, asyncio.CancelledError)):
                # Tokens already spent are still receipted.
                timed_out = isinstance(exc, (TimeoutError, httpx.TimeoutException))
                failure = {'status': 'unsupported', 'text': 'Sorry, that question timed out. Please try again.' if timed_out
                           else 'Sorry, I could not answer that. Please try again.',
                           'snapshot': payload.snapshot.model_dump(mode='json'), 'mode': self.agent.mode, 'offers': [],
                           'evidence': [], 'usage': usage_dict(usage, time.perf_counter() - started)}
            try:
                await asyncio.shield(asyncio.to_thread(self.repository.fail, token, turn['id'], failure))
            except RuleError:
                pass
            if failure is None:
                raise
            # The exception chain's messages (validation steps, the model API's error text) carry no credentials:
            # keys travel in headers, never in messages. Capped.
            detail = ' <- '.join(str(e) for e in _chain(exc) if str(e))[:600]
            logging.getLogger(__name__).warning('Question %s failed: %s %s', turn['id'], type(exc).__name__, detail)
            return failure

    async def _answer(self, prompt, row, here, match, info, payload, usage, started, single=False):
        """One answer from `match` (another live match when `info` is given: marked with its header). Returns
        (reply, draft, offers). single: an answer within a several-match request, scoped to this match alone."""
        stats, compact = await asyncio.gather(self.match_data.stats(payload.snapshot),
                                              self.narratives.compact(payload.snapshot))
        trends = await self.match_data.trends(payload.snapshot) if hasattr(self.match_data, 'trends') else []
        # The match's audience choice overrides the account's defaults; names stay private.
        profile = {**(await self.profile(row['profile_id']))['selections'],
                   **((row.get('audience') or {}).get('selections') or {})}
        history = [{'user': t['prompt'], 'reply': {key: t['reply'].get(key) for key in (
            'status', 'answer_kind', 'text', 'clarification', 'goal', 'statistic_request', 'standard_stat_id')}}
            for t in row['turns'][-12:] if t['reply']]
        replay_config = await self.config.get('replay-timing')
        toolkit = QuestionTools(payload, self.match_data, self.narratives, self.planner, stats['stats'], compact,
                                history, replay_config)
        # The live matches (teams, minute played): askable, and answerable as a list.
        live = await self.cross.listing(here, None if info else payload.snapshot) if self.cross else []
        if single:  # this part answers for its match alone; the other matches get their own parts
            live = [entry for entry in live if entry['match_id'] == match.match_id]
        for entry in live:
            toolkit.evidence['match:' + entry['match_id']] = {
                'id': 'match:' + entry['match_id'], 'kind': 'match', 'label': ' v '.join(entry['teams'])}
        # Multi-minute measures (field tilt, pressing...) as ETL serves them: an answer about one cites its value.
        # Grouped per trend (about 190 rows otherwise): values by team id and window; the id is derived, not listed.
        names = {t['id']: t['name'] for t in payload.teams}
        served = {}
        for trend in trends:
            identifier = f"trend:{trend['trendId']}:{trend['contestantId']}:{trend['window']}"
            team = names.get(trend['contestantId'], trend['contestantId'])
            label = f"{trend.get('label') or trend['trendId']} ({team}, {WINDOWS.get(trend['window'], trend['window'])})"
            toolkit.evidence[identifier] = {'id': identifier, 'kind': 'trend', 'label': label, 'value': trend['value']}
            entry = served.setdefault(trend['trendId'], {'trend': trend['trendId'], 'label': trend.get('label'),
                                                         'meaning': trend.get('meaning'), 'unit': trend.get('unit'),
                                                         'values': {}})
            value = trend['value']
            entry['values'].setdefault(trend['contestantId'], {})[trend['window']] = \
                round(value, 3) if isinstance(value, float) else value
        served = list(served.values())
        context = {'snapshot': payload.snapshot.model_dump(), 'teams': payload.teams, 'players': payload.players,
            'live_matches': [{**entry, 'evidence_id': 'match:' + entry['match_id']} for entry in live],
            'trends': served,
            'data_reference': payload.data_reference, 'profile': profile, 'history': history,
            'standard_stats': [{**s, 'evidence_id': 'stat:' + s['id']} for s in model_catalogue(stats['stats'])],
            'compact': {**compact, 'tail': [toolkit._event_reference(e) for e in compact.get('tail', [])[:100]],
                        'tail_truncated': len(compact.get('tail', [])) > 100,
                        'key_events': [toolkit._event_reference(e) for e in compact.get('key_events', [])[-100:]]}}
        if single:
            context['single_match'] = True
        draft = QuestionDraft.model_validate(await self.agent.answer(prompt, context, toolkit))
        draft = await resolve_answer(draft, toolkit)
        if any(identifier not in toolkit.evidence for identifier in draft.evidence_ids):
            raise ValueError('Unverified evidence reference')
        offers = toolkit.offers if draft.status == 'answer' else []
        if offers:
            # Stat values come from ETL or deterministic evaluation, never model prose.
            draft.text = toolkit.answer_text or ' '.join(stat_answer(offer) for offer in offers)
        if draft.status == 'unsupported' and draft.answer_kind == 'replay':
            # Statistic and routing refusals carry checked fixed reasons; replay prose does not.
            draft.text = UNAVAILABLE
        replay = None
        if draft.answer_kind == 'replay' and draft.status == 'answer' and draft.replay_items:
            items = [item.model_dump() for item in draft.replay_items]
            await toolkit.replay.load()  # Summary plans may cite only key moments.
            edge = await self.replays.edge(payload.snapshot, self._video(match))
            replay = {**self.replays.build(toolkit.replay, items, edge=edge), 'items': items,
                      'refine_offer': draft.refine_offer, 'derived': toolkit.replay.derived}
        reply = QuestionReply(**draft.model_dump(), snapshot=payload.snapshot, offers=offers,
            evidence=[toolkit.evidence[i] for i in draft.evidence_ids], mode=self.agent.mode,
            goal=toolkit.goal if offers else None, replay=replay,
            usage=usage_dict(usage, time.perf_counter() - started),
            other_match=header(match, info) if info else None).model_dump(mode='json')
        return reply, draft, offers

    async def _follow_offer(self, prompt, draft, offers, other_match):
        """{prompt, other_match} when the decision model judges a non-statistic question to be about a developing
        story (config `follow-offer`), answered or not (a story the chat cannot answer yet is one to follow); never for
        stats or clarifications, never blocking the answer when it fails."""
        if self.decide is None or draft.status not in ('answer', 'unsupported') or draft.answer_kind == 'statistic' \
                or offers:
            return None
        try:
            config = await self.config.get('follow-offer')
            if not config.enabled or not self._offers.take(config.max_per_minute):
                return None
            probability = await asyncio.wait_for(self.decide.probability(
                decision_state(prompt, draft.text), config.instructions, config.true, config.false,
                config.timeout_seconds), config.timeout_seconds)
        except Exception as exc:  # the offer is optional; the answer is not
            logging.getLogger(__name__).info('Follow offer skipped: %s', type(exc).__name__)
            return None
        return {'prompt': prompt[:300], 'other_match': other_match} if probability >= config.min_probability else None

    @staticmethod
    def _video(match):
        return bool(((match.info or {}).get('capabilities') or {}).get('video'))

    async def replay_page(self, match_id, token, turn_id, page):
        """Another page of a saved replay, re-cut against a fresh snapshot. No model call."""
        row = await self.read(match_id, token)
        turn = next((t for t in row['turns'] if t['id'] == turn_id and t['reply']), None)
        saved = turn and turn['reply'].get('replay')
        config = await self.config.get('replay-timing')
        if not saved or not 0 <= page < saved.get('page_count', config.max_items):
            raise RuleError('replay_not_found', 'That replay page is not available.', 404)
        # A replay from another match's answer re-cuts against that match (404 once it is cleared).
        match = self.registry.get((turn['reply'].get('other_match') or {}).get('id') or match_id)
        payload = await self.match_data.capture(match)
        tools = ReplayTools(payload.snapshot, self.match_data, self.narratives, payload.players, payload.teams, config)
        await tools.load()
        if any(item['kind'] == 'key_moment' for item in saved['items']):
            await tools.key_moments()
        tools.cited |= {item['source_id'] for item in saved['items'] if item['kind'] == 'event' and item['source_id'] in tools.events}
        edge = await self.replays.edge(payload.snapshot, self._video(match))
        return {**self.replays.build(tools, saved['items'], page, until=saved.get('observed_until'), edge=edge),
                'items': saved['items'], 'refine_offer': saved.get('refine_offer'), 'derived': saved.get('derived')}

    async def track(self, match_id, token, offer_id):
        async with self._locks(match_id):
            row = await self.read(match_id, token)
            offer = await asyncio.to_thread(self.repository.offer, token, offer_id)
            document = offer['document']
            here = match = self.registry.get(match_id)
            if document.get('match_id') != row['match_id']:
                # A stat from another live match (a cross-match answer's offer) is pinned from it.
                if self.cross is None:
                    raise RuleError('wrong_match', 'This offer belongs to another match.', 409)
                match = await self.cross.other(match_id, document.get('match_id'))
            if document.get('kind') == 'standard':
                payload = await self.match_data.capture(match)
                stats = await self.match_data.stats(payload.snapshot)
                stat = next((s for s in stats['stats'] if s['id'] == document['standard_stat_id']), None)
                if not stat or not stat.get('available') or not stat.get('complete'):
                    raise RuleError('stat_unavailable', 'This statistic is temporarily unavailable.', 503)
                calculation = {**stat, 'id': pin_id(document), 'kind': 'standard', 'standard_stat_id': stat['id']}
            else:
                calculation = await match.register(Rule.model_validate(document['rule']), document['label'])
            if match is not here:
                calculation = {**calculation, 'id': viewer_pin_id(document, match_id)}
            # Registration releases the match lock. Fence the durable link too: a purge in
            # between must not mark a deleted rule tracked.
            async with here.guard():
                await asyncio.to_thread(self.repository.tracked, token, offer_id, calculation['id'])
            return {'offer_id': str(offer_id), 'calculation': calculation, 'tracked': True}


def _chain(exc):
    """The exception and its causes, outermost first. A `raise … from None` (the model adapter hiding provider bodies)
    ends the chain."""
    while exc is not None:
        yield exc
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
