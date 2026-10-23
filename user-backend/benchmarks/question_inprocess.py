"""Opt-in in-process question golden set (no API, database or stack): snapshots of the shipped recording, standard
stats from ETL's reference catalogue, the context QuestionService._ask builds. `--agent fixture` runs the doubles.
"""
import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

from benchmarks.doubles.recording import FixtureEventSource
from benchmarks.doubles.config import seeded
from benchmarks.doubles.recaps import build_recaps
from benchmarks.doubles.spadl import ma3_rows
from backend.adapters.match_data import periods
from backend.adapters.ma3 import card, score
from backend.models.actions import SpadlAction
from backend.adapters.ma3 import stat
from backend.adapters.usage import as_dict, start_usage
from backend.agents.workflow import workflow_from_env
from backend.models.questions import MatchSnapshot, QuestionDraft, SnapshotInput
from backend.services.observed import observed
from backend.models.stat_offers import stat_answer
from backend.services.question_answers import model_catalogue, resolve_answer
from backend.services.question_tools import QuestionTools
from benchmarks.evaluate_questions import check

ROOT = Path(__file__).resolve().parents[2]


def catalogue_inputs(spec, recording):
    """The recording as the rows ETL writes: matches (MA1 capabilities, home), matchTeams,
    canonicalEvents, possessionSamples, spadlActions (etl/reference/spadl.py) and rawEvents (MA3)."""
    from reference import spadl
    camel = lambda key: re.sub(r'_(\w)', lambda m: m.group(1).upper(), key)
    caps = {('eventTypes' if k == 'supported_event_types' else camel(k)): v for k, v in spec['capabilities'].items()}
    teams = [{'contestantId': t['id'], 'name': t['name'], 'position': 'home' if i == 0 else 'away'}
             for i, t in enumerate(spec['teams'])]
    events = []
    for e in spec['events']:
        q = {x['type']: x['value'] for x in e['qualifiers']}
        events.append({'eventId': e['eventId'], 'seq': e['sequence'], 'revision': e.get('revision', 1),
                       'deleted': e.get('deleted', False), 'eventType': e['typeName'], 'teamId': e['teamId'],
                       'bodyPart': q.get('bodyPart'), 'outcome': e['outcome'], 'qualifiers': json.dumps(q),
                       'videoSeconds': e['videoSeconds']})
    samples = [{'sampleId': i, 'videoSeconds': s['video_seconds'], 'contestantId': s['team_id'],
                'durationSeconds': s['duration_seconds']}
               for i, s in enumerate(sorted(spec['possession_samples'], key=lambda s: s['video_seconds']), 1)]
    home = teams[0]['contestantId']
    raw = ma3_rows(recording)
    match = {'capabilities': json.dumps(caps), 'homeContestantId': home}
    return match, teams, events, samples, spadl.actions(raw, home), raw


class Upstream:
    """In-process match data: observed events at the snapshot, ETL's catalogue and recaps."""
    def __init__(self, spec=None, recording=None):
        self.inputs, self.payloads = catalogue_inputs(spec, recording), {}

    async def capture(self, payload, **_):
        self.payloads[payload.snapshot.id] = payload

    async def stats(self, snapshot):
        from reference import catalogue
        match, teams, events, samples, actions, raw = self.inputs
        rows = catalogue.stats_at_seq(match, teams, events, samples, snapshot.seq, snapshot.seq,
                                      actions=actions, raw=raw)
        return {'stats': [stat(row) for row in rows]}

    async def actions(self, snapshot, offset=0, limit=100, start=None, end=None, actionType=None, playerId=None,
                      teamId=None, period=None, **_):
        offset, limit = offset or 0, limit or 100
        rows = [a.row() for a in self.payloads[snapshot.id].actions
                if (start is None or a.match_time_seconds >= start) and (end is None or a.match_time_seconds < end)
                and (actionType is None or a.action_type == actionType) and (playerId is None or a.player_id == playerId)
                and (teamId is None or a.team_id == teamId) and (period is None or a.period == period)]
        return {'items': rows[offset:offset + limit], 'has_more': offset + limit < len(rows), 'total': len(rows),
                'complete': True}

    def _cards(self, seq):
        return [card({**m, 'payload': json.dumps(m)}) for m in self.inputs[5] if m['typeId'] == 17 and m['eventSeq'] <= seq]

    async def cards(self, snapshot):
        return self._cards(snapshot.seq)

    async def score(self, snapshot, teams):
        return score([{**m, 'payload': json.dumps(m)} for m in self.inputs[5]
                      if m['typeId'] in (16, 900) and m['eventSeq'] <= snapshot.seq], teams)

    async def periods(self, snapshot):
        return periods(self.payloads[snapshot.id].events)

    def snapshot_actions(self, match_id, seq):
        """ETL's final SPADL actions a snapshot at seq reads (team-relative, as the backend holds them)."""
        home = self.inputs[1][0]['contestantId']
        return [SpadlAction.from_row(a, match_id, home) for a in self.inputs[4] if a['finalSeq'] <= seq]

    def _recaps(self, snapshot):
        payload = self.payloads[snapshot.id]
        return build_recaps(payload, observed(payload.events), self._cards(snapshot.seq))

    async def compact(self, snapshot):
        recaps = self._recaps(snapshot)
        recaps.pop('archive')
        return recaps

    async def recaps(self, snapshot, ids=None, tier=None, start=None, end=None, offset=0, limit=30, **_):
        rows = [r for r in self._recaps(snapshot)['archive'] if (not ids or r['id'] in ids)
                and (not tier or r['tier'] == tier) and (start is None or r['end_seconds'] > start)
                and (end is None or r['start_seconds'] < end)]
        return {'items': rows[offset:offset + limit], 'has_more': offset + limit < len(rows)}


def cursor_at(events, at):
    if at in (None, 'end'):
        return len(events)
    if at == 'halftime':
        return next(i + 1 for i, e in enumerate(events) if e.event_type == 'period_end' and e.period == 1)
    minutes, seconds = at['clock'].split(':')
    target = (at['period'], int(minutes) * 60 + int(seconds))
    return max(i + 1 for i, e in enumerate(events) if (e.period, e.match_time_seconds) <= target)


REFERENCE = 'full'  # --reference: the A/B variant of the agents' SPADL context.


def reference(source):
    """full: the SPADL dictionary with definitions (runtime). compact: enum names and availability only;
    definitions are left to lookup_spadl. A benchmark-only variant for comparing accuracy."""
    data = source.data_reference()
    if REFERENCE == 'compact':
        data = {key: data[key] for key in ('contract_id', 'capabilities', 'availability', 'outside_spadl', 'unavailable')
                if key in data} | {kind: list(data[kind]) for kind in ('events', 'results', 'bodyparts', 'zones')}
    return data


def snapshot(source, cursor, upstream):
    events = list(source.history(cursor))
    last = events[-1]
    return SnapshotInput(snapshot=MatchSnapshot.at(source.match_id, cursor, last, 'in-process'),
        events=events, actions=upstream.snapshot_actions(source.match_id, cursor), teams=source.spec['teams'],
        players=source.spec['players'], data_reference=reference(source))


async def ask(agent, planner, source, match_data, narratives, cursor, prompt, history):
    payload = snapshot(source, cursor, match_data)
    await match_data.capture(payload)
    await narratives.capture(payload)
    stats, compact = await match_data.stats(payload.snapshot), await narratives.compact(payload.snapshot)
    toolkit = QuestionTools(payload, match_data, narratives, planner, stats['stats'], compact, history,
                            seeded('replay-timing'))
    context = {'snapshot': payload.snapshot.model_dump(), 'teams': payload.teams, 'players': payload.players,
               'data_reference': payload.data_reference, 'profile': {'team': 'home', 'fan_style': 'analytical'},
               'history': history,
               'standard_stats': [{**s, 'evidence_id': 'stat:' + s['id']} for s in model_catalogue(stats['stats'])],
               'compact': {**compact, 'tail': [toolkit._event_reference(e) for e in compact.get('tail', [])[:100]],
                           'tail_truncated': len(compact.get('tail', [])) > 100,
                           'key_events': [toolkit._event_reference(e) for e in compact.get('key_events', [])[-100:]]}}
    draft = QuestionDraft.model_validate(await agent.answer(prompt, context, toolkit))
    draft = await resolve_answer(draft, toolkit)
    offers = toolkit.offers if draft.status == 'answer' else []
    if offers:
        draft.text = toolkit.answer_text or ' '.join(stat_answer(offer) for offer in offers)
    return {**draft.model_dump(mode='json'), 'snapshot': payload.snapshot.model_dump(), 'offers': offers,
            'goal': toolkit.goal if offers else None}


async def run(args, suite):
    sys.path.insert(0, str(ROOT / 'etl'))  # ETL owns the standard stat catalogue.
    source = FixtureEventSource(ROOT / suite['recording'])
    match_data = narratives = Upstream(source.spec, ROOT / suite['recording'])
    if args.agent == 'local':
        from backend.agents.question import QuestionAgent
        planner, agent = workflow_from_env(data_reference=reference(source)), QuestionAgent()
        if planner is None:
            raise SystemExit('Configure the local model (LOCAL_LLM_*) or pass --agent fixture.')
    else:
        # Scripted model decisions through the real agent, planner, compiler and answers.
        from backend.agents.orchestrator import GoalAgent
        from backend.agents.question import QuestionAgent
        from backend.agents.workflow import RuleWorkflow
        from benchmarks.doubles.agents import FixtureCodingAgent
        from benchmarks.doubles.question_agent import ScriptedModel
        model = ScriptedModel()
        planner = RuleWorkflow(GoalAgent(model), FixtureCodingAgent(), source='fixture')
        agent = QuestionAgent(settings=object(), router=model, replay=object())
    rows, history = [], []
    for case in suite['cases']:
        if args.case_id and case['id'] not in args.case_id:
            continue
        if args.agent == 'fixture':
            if 'fixture' not in case:
                continue  # Prose answers (match, football) need the model.
            model.script = case['fixture']
        if 'at' in case:
            history = []  # A timed case is its own conversation.
        started, usage = time.perf_counter(), start_usage()
        try:
            async with asyncio.timeout(args.case_timeout):
                body = await ask(agent, planner, source, match_data, narratives,
                                 cursor_at(source.events, case.get('at')), case['prompt'], history)
            checks = check(case, body, source.match_id)
        except Exception as exc:  # Record and continue; the type only, never provider bodies.
            body, checks = {'error': type(exc).__name__}, {'completed': False}
        row = {'id': case['id'], 'prompt': case['prompt'], 'ok': all(checks.values()), 'checks': checks,
               'usage': as_dict(usage, time.perf_counter() - started), 'text': body.get('text'),
               'status': body.get('status'), 'error': body.get('error'),
               'offers': [[o.get('standard_stat_id') or o.get('label'), o.get('value')] for o in body.get('offers', [])]}
        rows.append(row)
        if 'status' in body:
            history.append({'user': case['prompt'], 'reply': {key: body.get(key) for key in (
                'status', 'answer_kind', 'text', 'clarification', 'goal', 'statistic_request', 'standard_stat_id')}})
        print(json.dumps({k: row[k] for k in ('id', 'ok', 'text', 'offers')} | {'seconds': row['usage']['seconds'],
              'tokens': row['usage']['input_tokens'] + row['usage']['output_tokens']}, ensure_ascii=False), flush=True)
    return rows


def summary(rows):
    seconds = [r['usage']['seconds'] for r in rows]
    tokens = [r['usage']['input_tokens'] + r['usage']['output_tokens'] for r in rows]
    return {'passed': sum(r['ok'] for r in rows), 'cases': len(rows),
            'median_seconds': round(statistics.median(seconds), 2), 'max_seconds': round(max(seconds), 2),
            'average_tokens': round(statistics.mean(tokens)), 'average_calls': round(
                statistics.mean(r['usage']['calls'] for r in rows), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--agent', choices=('local', 'fixture'), default='local')
    parser.add_argument('--case-id', action='append')
    parser.add_argument('--case-timeout', type=float, default=90)
    parser.add_argument('--reference', choices=('full', 'compact'), default='full')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    suite = json.loads(Path(__file__).with_name('question_cases.json').read_text())
    global REFERENCE
    REFERENCE = args.reference
    rows = asyncio.run(run(args, suite))
    result = {'summary': summary(rows), 'cases': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
