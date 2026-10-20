"""Per-question bounded tools and deterministic one-off custom-stat offers."""
import json
from uuid import uuid4
from typing import get_args
from backend.models.events import Event, EventType
from backend.models.recording import MAX_RECORDING_EVENTS
from backend.services.filter_engine import FilterEngine
from backend.services.rule_availability import unsupported_reason, observed_unattributed_events, incomplete_player_rule
from backend.services.replay import ReplayTools
from backend.services.question_answers import model_catalogue

class QuestionTools:
    def __init__(self, payload, match_data, narratives, planner, stats, compact, history):
        self.payload, self.match_data, self.narratives, self.planner = payload, match_data, narratives, planner
        self.stats, self.compact, self.history = stats, compact, history
        self.calls, self.offers, self.goal, self.evidence = 0, [], None, {}
        self.prepared_results = {}
        self._replay = None
        for row in stats:
            self.evidence['stat:' + row['id']] = {'id':'stat:' + row['id'], 'kind':'stat', 'label':row['label']}
        for row in compact.get('blocks', []):
            self.evidence[row['id']] = {'id':row['id'],'kind':'recap','label':f"{row['start_seconds']//60}–{row['end_seconds']//60}′ recap"}
        for row in compact.get('tail', []) + compact.get('key_events', []):
            self._event_reference(row)

    @property
    def replay(self):
        if self._replay is None:
            self._replay = ReplayTools(self.payload.snapshot, self.match_data, self.narratives,
                                       self.payload.players, self.payload.teams)
        return self._replay

    def _event_reference(self, row):
        identifier = 'event:' + row['event_id'] + ':' + str(row['revision'])
        self.evidence[identifier] = {'id':identifier, 'kind':'event', 'label':f"{row['match_time_seconds']//60}′ {row['event_type']}"}
        return {**row, 'evidence_id':identifier}

    def _call(self):
        self.calls += 1
        if self.calls > 6:
            raise ValueError('Question tool budget exhausted')

    async def standard(self, ids=None):
        self._call()
        rows = self.stats if not ids else [r for r in self.stats if r['id'] in ids]
        if ids and len(rows) != len(set(ids)):
            return {'unavailable':True, 'message':'Unknown standard statistic'}
        return {'stats':[{**r,'evidence_id':'stat:' + r['id']} for r in rows]}

    async def events(self, start=None, end=None, event_type=None, player_id=None, offset=0, period=None, *, end_inclusive=False):
        self._call()
        if end_inclusive and end is not None:
            # Canonical timestamps are integer seconds; preserve one upstream [start,end) contract.
            end += 1
        if offset < 0 or (start is not None and start < 0) or (end is not None and start is not None and end <= start):
            return {'unavailable':True,'message':'Invalid event interval'}
        if event_type is not None and event_type not in get_args(EventType):
            return {'unavailable':True,'message':'This event category is not recorded.'}
        capabilities = self.payload.data_reference.get('capabilities')
        if capabilities and event_type is not None and event_type not in capabilities.get('supported_event_types', ()):
            return {'unavailable':True,'message':'This recording does not capture that event category.'}
        if player_id is not None and player_id not in {p['id'] for p in self.payload.players}:
            return {'unavailable':True,'message':'This player is not in the match.'}
        if period is not None and period not in range(1,6):
            return {'unavailable':True,'message':'Invalid match period.'}
        page = await self.match_data.events(self.payload.snapshot, start=start, end=end, eventType=event_type, playerId=player_id, offset=offset, limit=100, period=period)
        page['items'] = [self._event_reference(r) for r in page['items']]
        return page

    async def recaps(self, ids=None, start=None, end=None, tier=None, offset=0):
        self._call()
        if offset < 0 or (start is not None and start < 0) or (end is not None and start is not None and end <= start):
            return {'unavailable':True,'message':'Invalid recap interval'}
        if tier is not None and self.compact.get('available_tiers') is not None and tier not in self.compact['available_tiers']:
            return {'unavailable':True,'message':'This recap tier is not available in the development adapter.'}
        page = await self.narratives.recaps(self.payload.snapshot, ids=ids, start=start, end=end, tier=tier, offset=offset, limit=30)
        for row in page['items']:
            self.evidence[row['id']] = {'id':row['id'],'kind':'recap','label':f"{row['start_seconds']//60}–{row['end_seconds']//60}′ recap"}
        return page

    async def prepare(self, request):
        self._call()
        result = await self._prepare(request)
        self.prepared_results[request] = result
        return result

    async def prepare_original(self):
        """Recover omitted intent without cutting off semantic constraints."""
        self._call()
        history = []
        for turn in self.history[-3:]:
            reply = turn['reply']
            # The validated goal is more useful than old result prose. Keep it whole.
            assistant = (json.dumps({'goal':reply['goal']}) if reply.get('goal') else
                         json.dumps(reply['clarification']) if reply.get('clarification') else
                         reply.get('statistic_request') or reply.get('text') or 'No previous answer.')
            history.extend([{'role':'user','content':turn['user']},
                            {'role':'assistant','content':assistant}])
        if any(len(row['content']) > 2000 for row in history) or sum(len(row['content']) for row in history) > 6000:
            result = {'status':'clarification', 'message':'Please restate the statistic and its time range in one message.'}
        else:
            result = await self._prepare(self.original_prompt, history=history)
        self.prepared_results[self.original_prompt] = result
        return result

    async def _prepare(self, request, history=None):
        if len(self.offers) >= 2:
            return {'status':'unsupported','message':'Ask for one statistic at a time.'}
        context = {'match_id':self.payload.snapshot.match_id,'players':self.payload.players,'teams':self.payload.teams,
                   'data_reference': self.payload.data_reference,
                   'standard_stats':model_catalogue(self.stats), 'clock_seconds':self.payload.snapshot.clock_seconds,
                   'period':self.payload.snapshot.period}
        outcome = await self.planner.plan(request, context, history=history) if history else await self.planner.plan(request, context)
        if outcome.status == 'clarification':
            return outcome.model_dump(mode='json')
        if outcome.status == 'reuse':
            row = next((r for r in self.stats if r['id'] == outcome.standard_stat_id), None)
            return {'status':'reuse','stat':row,'evidence_id':'stat:' + outcome.standard_stat_id}
        if outcome.status != 'ready' or outcome.rule is None:
            # A declined plan names its missing data; workflow failures stay generic.
            return {'status':'unsupported','message':outcome.message if outcome.status == 'unsupported' else None}
        if reason := unsupported_reason(outcome.rule, self.payload.data_reference.get('capabilities')):
            return {'status':'unsupported', 'message':reason}
        # Complete observed history, not a model-visible truncated search page.
        engine, offset, observed = FilterEngine(), 0, []
        while True:
            page = await self.match_data.events(self.payload.snapshot, offset=offset, limit=100)
            if not page.get('complete') or (page.get('has_more') and not page['items']):
                raise ValueError('Incomplete history')
            for row in page['items']:
                event = Event.model_validate(row)
                if event.match_id != self.payload.snapshot.match_id:
                    raise ValueError('Wrong match event')
                engine.ingest(event)
                observed.append(event)
            offset += len(page['items'])
            if offset > MAX_RECORDING_EVENTS:
                raise ValueError('History limit exceeded')
            if not page.get('has_more'):
                break
        if incomplete_player_rule(outcome.rule, observed_unattributed_events(observed)):
            return {'status': 'unsupported', 'message': 'Some matching events have no recorded player, so a complete player total is unavailable.'}
        result = engine.register(outcome.rule)
        offer = {'id':str(uuid4()),'label':outcome.goal.description[:160] if outcome.goal else request[:160],
                 'value':result.value,'unit':outcome.rule.unit,'rule':outcome.rule.model_dump(mode='json'),
                 'goal':outcome.goal.model_dump(mode='json') if outcome.goal else None,
                 'snapshot_id':self.payload.snapshot.id,'run_id':self.payload.snapshot.run_id}
        leaves = outcome.rule.inputs if outcome.rule.composite else (outcome.rule,)
        if any(leaf.coverage == 'recorded' for leaf in leaves) and not offer['label'].lower().startswith('recorded'):
            offer['label'] = 'Recorded ' + offer['label'][:151]
        self.offers.append(offer)
        self.goal = offer['goal']
        identifier = 'offer:' + offer['id']
        self.evidence[identifier] = {'id':identifier,'kind':'stat','label':offer['label']}
        return {'status':'ready','offer_id':offer['id'],'label':offer['label'],'value':offer['value'],'unit':offer['unit'],'evidence_id':identifier,
                'message':'One-off result. A Track this stat card will be shown; tracking has not started.'}
