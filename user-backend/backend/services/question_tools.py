"""Per-question bounded tools and deterministic one-off custom-stat offers."""
import json
from decimal import Decimal
from uuid import uuid4
from typing import get_args
from backend.models.actions import ActionType
from backend.models.events import minute_label
from backend.models.stat_offers import comparison_offer
from backend.services.filter_engine import FilterEngine
from backend.services.spadl_lookup import lookup
from backend.services.rule_availability import unsupported_reason, observed_unattributed_events, incomplete_player_rule
from backend.services.replay import ReplayTools
from backend.services.question_answers import PER_TEAM, model_catalogue
import re

class QuestionTools:
    def __init__(self, payload, match_data, narratives, planner, stats, compact, history, replay_config=None):
        self.payload, self.match_data, self.narratives, self.planner = payload, match_data, narratives, planner
        self.replay_config = replay_config  # models/config.Replay
        self.stats, self.compact, self.history = stats, compact, history
        self.calls, self.offers, self.goal, self.evidence = 0, [], None, {}
        self.prepared_results, self.answer_text = {}, None
        self._replay = None
        for row in stats:
            self.evidence['stat:' + row['id']] = {'id':'stat:' + row['id'], 'kind':'stat', 'label':row['label']}
        for row in compact.get('blocks', []):
            self.evidence[row['id']] = {'id':row['id'],'kind':'recap','label':recap_label(row)}
        for row in compact.get('tail', []) + compact.get('key_events', []):
            self._event_reference(row)

    @property
    def replay(self):
        if self._replay is None:
            self._replay = ReplayTools(self.payload.snapshot, self.match_data, self.narratives,
                                       self.payload.players, self.payload.teams, self.replay_config)
        return self._replay

    def _event_reference(self, row):
        """Evidence for one SPADL action (`a{actionId}`) or one MA3 card (`card:{id}`)."""
        identifier = row['id'] if row['id'].startswith('card:') else 'action:' + row['id']
        minute = minute_label(row['period'], row['match_time_seconds'])
        what = (f"{row['colour'].replace('_', ' ')} card" if 'colour' in row else
                ' '.join(part for part in (row['action_type'], row.get('result')) if part).replace('_', ' '))
        self.evidence[identifier] = {'id':identifier, 'kind':'event', 'label':f"{minute} {what}"}
        # The label prose must use, so text and evidence never disagree (51:18 is 52′).
        return {**row, 'evidence_id':identifier, 'minute':minute}

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

    async def actions(self, start=None, end=None, action_type=None, player_id=None, offset=0, period=None,
                      team_id=None, *, end_inclusive=False):
        self._call()
        if end_inclusive and end is not None:
            end += 1  # Action clocks are whole seconds; keep one upstream [start,end) contract.
        if offset < 0 or (start is not None and start < 0) or (end is not None and start is not None and end <= start):
            return {'unavailable':True,'message':'Invalid action interval'}
        if action_type is not None and action_type not in get_args(ActionType):
            return {'unavailable':True,'message':'Not a SPADL action type.', 'action_types': list(get_args(ActionType))}
        if player_id is not None and player_id not in {p['id'] for p in self.payload.players}:
            return {'unavailable':True,'message':'This player is not in the match.'}
        if team_id is not None and team_id not in {t['id'] for t in self.payload.teams}:
            return {'unavailable':True,'message':'This team is not in the match.'}
        if period is not None and period not in range(1,6):
            return {'unavailable':True,'message':'Invalid match period.'}
        page = await self.match_data.actions(self.payload.snapshot, start=start, end=end, actionType=action_type,
                                             playerId=player_id, teamId=team_id, offset=offset, limit=100, period=period)
        page['items'] = [self._event_reference(compact_action(r)) for r in page['items']]
        return page

    async def cards(self):
        """Cards shown so far (outside SPADL)."""
        self._call()
        return {'items': [self._event_reference(row) for row in await self.match_data.cards(self.payload.snapshot)]}

    def lookup(self, term):
        """The SPADL contract for one term (no match data; not budgeted)."""
        return lookup(term, self.stats)

    async def recaps(self, ids=None, start=None, end=None, tier=None, offset=0):
        self._call()
        if offset < 0 or (start is not None and start < 0) or (end is not None and start is not None and end <= start):
            return {'unavailable':True,'message':'Invalid recap interval'}
        if tier is not None and self.compact.get('available_tiers') is not None and tier not in self.compact['available_tiers']:
            return {'unavailable':True,'message':'This recap tier is not available.'}
        page = await self.narratives.recaps(self.payload.snapshot, ids=ids, start=start, end=end, tier=tier, offset=offset, limit=30)
        for row in page['items']:
            self.evidence[row['id']] = {'id':row['id'],'kind':'recap','label':recap_label(row)}
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
            ids = outcome.standard_stat_ids or [outcome.standard_stat_id]
            rows = [next((r for r in self.stats if r['id'] == i), None) for i in ids]
            return {'status':'reuse','stat':rows[0],'stats':rows,'formula':outcome.formula,
                    'evidence_id':'stat:' + ids[0]}
        if outcome.status != 'ready' or outcome.rule is None:
            # A declined plan names its missing data; workflow failures stay generic.
            return {'status':'unsupported','message':outcome.message if outcome.status == 'unsupported' else None}
        if reason := unsupported_reason(outcome.rule, self.payload.data_reference.get('capabilities')):
            return {'status':'unsupported', 'message':reason}
        # Every final SPADL action at the snapshot, not a model-visible search page.
        engine, observed = FilterEngine(), list(self.payload.actions)
        if any(action.match_id != self.payload.snapshot.match_id or action.final_seq > self.payload.snapshot.seq
               for action in observed):
            raise ValueError('Action outside the snapshot')
        for action in observed:
            engine.ingest(action)
        if outcome.goal is not None and outcome.goal.rank_by == 'player':
            return self._ranking(outcome.goal, engine, observed)
        goals = per_team(outcome.goal, request, self.payload.teams) or [outcome.goal]
        offers = []
        for goal in goals:
            rule = goal.target_rule(self.payload.snapshot.match_id) if goal is not outcome.goal else outcome.rule
            if incomplete_player_rule(rule, observed_unattributed_events(observed)):
                return {'status': 'unsupported', 'message': 'Some matching actions have no recorded player, so a complete player total is unavailable.'}
            offers.append(self._offer(goal, rule, engine.register(rule).value, request))
        if len(offers) > 1:
            sides = [{**offer, 'team_id': goal.team_ids[0]} for goal, offer in zip(goals, offers)]
            offers = [comparison_offer(sides, outcome.goal.description, self.payload.teams,
                                       outcome.goal.model_dump(mode='json'))]
            identifier = offers[0]['id']
            self.evidence['offer:' + identifier] = {'id': 'offer:' + identifier, 'kind': 'stat',
                                                    'label': offers[0]['label']}
        self.offers.extend(offers)
        self.goal = offers[0]['goal']
        offer = offers[0]
        return {'status':'ready','offer_id':offer['id'],'offer_ids':[o['id'] for o in offers],'label':offer['label'],
                'value':offer['value'],'unit':offer['unit'],'evidence_id':'offer:' + offer['id'],
                'message':'One-off result. A Track this stat card will be shown; tracking has not started.'}

    def _ranking(self, goal, engine, observed):
        """Players ranked by the goal's measure over the snapshot's SPADL actions (no model counts).
        Every tied leader is named; up to three are offered for tracking."""
        teams = {t['id']: t['name'] for t in self.payload.teams}
        match_id = self.payload.snapshot.match_id
        candidates = [p for p in self.payload.players if (not goal.team_ids or p.get('team_id') in goal.team_ids)
                      and (not goal.player_ids or p['id'] in goal.player_ids)]
        # One pass: a player's total is the whole goal's contribution of that player's actions.
        whole, totals = goal.model_copy(update={'rank_by': None}).target_rule(match_id), {}
        for event in observed:
            if event.player_id is not None and (value := whole.contribution(event)):
                totals[event.player_id] = totals.get(event.player_id, Decimal(0)) + Decimal(str(value))
        rows = sorted(((float(totals.get(p['id'], 0)), p) for p in candidates), key=lambda row: -row[0])
        single = lambda player: goal.model_copy(update={'player_ids': (player['id'],), 'rank_by': None,
                                                         'description': f"{player['name']}: {goal.description}"[:500]})
        unit = '' if goal.operation == 'count' else ' m'
        if not rows or not rows[0][0]:
            return {'status': 'ranking', 'offer_ids': [], 'text': f"{goal.description}: no player has any yet."}
        top = rows[0][0]
        leaders = [row for row in rows if row[0] == top]
        name = lambda row: row[1]['name'] + (f" ({teams[row[1]['team_id']]})" if not goal.team_ids and row[1].get('team_id') in teams else '')
        shown = [name(row) for row in leaders[:6]] + ([f"{len(leaders) - 6} others"] if len(leaders) > 6 else [])
        names = shown[0] if len(shown) == 1 else ', '.join(shown[:-1]) + ' and ' + shown[-1]
        value = lambda v: format(v, '.1f').rstrip('0').rstrip('.') if isinstance(v, float) else str(v)
        text = (f"{goal.description} — leader: {names}, {value(top)}{unit}." if len(leaders) == 1 else
                f"{goal.description} — joint leaders: {names}, {value(top)}{unit} each.")
        chasing = [row for row in rows[len(leaders):len(leaders) + 3] if row[0]]
        if chasing:
            text += ' Next: ' + ', '.join(f"{name(row)} {value(row[0])}{unit}" for row in chasing) + '.'
        offers = []
        for _, player in leaders[:3]:  # Offered values come from the rule engine itself.
            leader = single(player)
            rule = leader.target_rule(match_id)
            offers.append(self._offer(leader, rule, engine.register(rule).value, leader.description))
        self.offers.extend(offers)
        self.goal = offers[0]['goal']
        return {'status': 'ranking', 'offer_ids': [o['id'] for o in offers], 'text': text,
                'evidence_ids': ['offer:' + o['id'] for o in offers]}

    def _offer(self, goal, rule, value, request):
        offer = {'id':str(uuid4()),'label':goal.description[:160] if goal else request[:160],
                 'value':value,'unit':rule.unit,'rule':rule.model_dump(mode='json'),
                 'goal':goal.model_dump(mode='json') if goal else None,
                 'snapshot_id':self.payload.snapshot.id,'match_id':self.payload.snapshot.match_id}
        leaves = rule.inputs if rule.composite else (rule,)
        if any(leaf.coverage == 'recorded' for leaf in leaves) and not offer['label'].lower().startswith('recorded'):
            offer['label'] = 'Recorded ' + offer['label'][:151]
        identifier = 'offer:' + offer['id']
        self.evidence[identifier] = {'id':identifier,'kind':'stat','label':offer['label']}
        return offer


def recap_label(row):
    """The recap's own broadcast label when it has one; else its minutes, e.g. [4380, 4440) is 74′."""
    if row.get('label'):
        return f"{row['label']} recap"
    first, last = row['start_seconds'] // 60 + 1, row['end_seconds'] // 60
    return f"{first}′ recap" if first >= last else f"{first}–{last}′ recap"


def per_team(goal, request, teams):
    """Split a measure into independently evaluated team goals, never a combined total."""
    if goal is None or goal.inputs or goal.player_ids or len(teams) < 2:
        return None
    split = PER_TEAM.search(f'{request} {goal.description}') or re.search(r'\bboth (?:team|side)s\b', request, re.I)
    if not (len(goal.team_ids) > 1 or (not goal.team_ids and split)):
        return None
    description = re.sub(r'\s*\b(?:split )?(?:for |by |per )?(?:each|both|every|per) (?:team|side)s?\b', '', goal.description).strip()
    return [goal.model_copy(update={'team_ids': (team['id'],), 'description': f"{team['name']}: {description}"[:500]})
            for team in teams if not goal.team_ids or team['id'] in goal.team_ids]


ACTION_KEYS = ('id', 'period', 'match_time_seconds', 'team_id', 'player_id', 'action_type', 'result', 'bodypart',
               'start_zone', 'end_zone', 'shot_outcome', 'save_kind', 'distance_metres', 'video_seconds')


def compact_action(row):
    """What a model sees of one action: SPADL names, no raw coordinates or provider ids."""
    return {key: row[key] for key in ACTION_KEYS if row.get(key) is not None}
