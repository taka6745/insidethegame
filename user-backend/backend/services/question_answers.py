"""Resolve the final declared source, never the last incidental tool invocation."""
from backend.models.events import minute_label
from backend.models.questions import QuestionDraft
from backend.models.stat_offers import stat_answer
from backend.agents.measurement_support import real_save_id
from uuid import uuid4
import re


UNAVAILABLE = 'Sorry, I cannot answer that from the information available.'


def unavailable(reason=None):
    """Name what is missing when known. Model-written reasons must stay short and number-free."""
    if not isinstance(reason, str) or not 0 < len(reason.strip()) <= 240 or re.search(r'[\d\n]', reason):
        return QuestionDraft(answer_kind='statistic',status='unsupported',text=UNAVAILABLE)
    return QuestionDraft(answer_kind='statistic',status='unsupported',text='Sorry, I cannot answer that. '+reason.strip())


def clear_offers(tools):
    tools.offers, tools.goal = [], None


def split_rows(row, stats):
    """A both-teams share equal to the sum of its team rows (possession) is a split: answer per team."""
    teams = team_rows(row, stats)
    if (row.get('team_id') is None and row.get('unit') == '%' and row.get('value') is not None
            and len(teams) > 1 and abs(sum(s['value'] for s in teams) - row['value']) < 0.5):
        return teams
    return [row]


def model_catalogue(stats):
    """Show models a both-teams share as its per-team split; a bare 100% invites long deliberation."""
    rows = []
    for row in stats:
        teams = split_rows(row, stats)
        if teams[0] is not row:
            name = row['label'].removeprefix('Both teams ')
            row = {**row, 'label': name[:1].upper() + name[1:] + ' split by team',
                   'value': {team['team_id']: team['value'] for team in teams},
                   'definition': row.get('definition', '') + ' Answered with each team share.'}
        rows.append(row)
    return rows


# "Each team", "per side", "split" ask for a per-team breakdown; "score" always means team goals.
PER_TEAM = re.compile(r'\b(?:each|per|by)\s+(?:team|side|club)s?\b|\b(?:each|apiece|respectively|split)\b', re.I)
SCORE = re.compile(r'\bscores?\b|\bscoreline\b', re.I)
SENT_OFF = re.compile(r'\bsent off\b|\bsending[- ]off\b|\bred cards?\b|\bdismiss|\bejected\b', re.I)


def wording(draft, tools):
    return f"{getattr(tools, 'original_prompt', None) or ''} {draft.statistic_request or ''}"


def team_rows(row, stats):
    kind = row['id'].split(':', 1)[-1]
    return [s for s in stats if s.get('team_id') and s['id'] == f"{s['team_id']}:{kind}"
            and s.get('available') and s.get('complete') and s.get('value') is not None]


def expand(row, stats, text):
    """Answer a both-teams row per team for shares, per-team wording and scores."""
    teams = team_rows(row, stats) if row.get('team_id') is None else []
    kind = row['id'].split(':', 1)[-1]
    if len(teams) > 1 and (PER_TEAM.search(text) or (kind == 'goals' and SCORE.search(text))):
        return teams
    return split_rows(row, stats)


def formula_text(formula, rows):
    """A ratio of two ETL rows, computed here; never by a model."""
    (a, b), values = rows, [row['value'] for row in rows]
    if formula == 'difference':
        return f"{a['label']} minus {b['label']}: {format_number(values[0] - values[1])}."
    if not values[1]:
        return f"{a['label']} as a share of {b['label']}: not available yet ({b['label']} is 0)."
    if formula == 'ratio':
        return f"{a['label']} per {b['label']}: {format_number(values[0] / values[1], 2)}."
    return (f"{a['label']} as a share of {b['label']}: {format_number(100 * values[0] / values[1])}% "
            f"({format_number(values[0])} of {format_number(values[1])}).")


def format_number(value, digits=1):
    return format(value, f'.{digits}f').rstrip('0').rstrip('.') if isinstance(value, float) else str(value)


def score_text(rows, text, score=None):
    """Both teams' goals read as a score, never as a combined count. `score`: goals per team from MA3 goals
    and VAR decisions (the catalogue's goals do not subtract VAR overturns yet)."""
    goals = [row for row in rows if row['id'].endswith(':goals') and row.get('team_id')]
    if not SCORE.search(text) or len(goals) != 2:
        return None, rows
    values = [(score or {}).get(row['team_id'], row['value']) for row in goals]
    names = [row['label'].removesuffix(' goals') for row in goals]
    return (f"Score: {names[0]} {values[0]}–{values[1]} {names[1]}.",
            [row for row in rows if row not in goals])


def standard_answer(draft, rows, tools, formula=None):
    clear_offers(tools)
    rows = [rows] if isinstance(rows, dict) or rows is None else rows
    missing = next((row for row in rows if not row or not row.get('available') or not row.get('complete')), False)
    if missing is not False:
        reason = missing and missing.get('unavailable_reason')
        return unavailable(missing and (f"{missing['label']} is not available. {reason}" if reason and len(reason) < 160
                                        and not re.search(r'[\d\n]', reason) else
                                        f"{missing['label']} is not available in this recording."))
    text, requested = wording(draft, tools), rows[0]['id']
    if formula:
        if (formula == 'percentage' and (rows[0].get('team_id') != rows[1].get('team_id') or rows[0]['value'] > rows[1]['value'])
                or any(row.get('unit') or not isinstance(row['value'], (int, float)) for row in rows)):
            return unavailable('Those statistics cannot be combined into that measure.')
        lead = formula_text(formula, rows)
    else:
        rows = list({item['id']: item for row in rows for item in expand(row, tools.stats, text)}.values())
        lead, rest = score_text(rows, text, getattr(tools, 'score', None))
    tools.offers = [{'id': str(uuid4()), 'kind': 'standard', 'standard_stat_id': item['id'],
                     'label': item['label'], 'value': item['value'],
                     'unit': item.get('unit', ''),
                     'snapshot_id': tools.payload.snapshot.id, 'match_id': tools.payload.snapshot.match_id}
                    for item in rows]
    tools.answer_teams = {row.get('team_id') for row in rows}
    shown = [] if formula else [offer for offer in tools.offers if offer['standard_stat_id'] in {r['id'] for r in rest}]
    tools.answer_text = ' '.join([lead or '', *(stat_answer(offer) for offer in shown)]).strip() if lead else None
    return QuestionDraft(answer_kind='statistic',status='answer',standard_stat_id=requested,
                         statistic_request=draft.statistic_request,
                         text=tools.answer_text or ' '.join(stat_answer(offer) for offer in tools.offers),
                         evidence_ids=['stat:'+item['id'] for item in rows])


def selected_answer(draft, identifiers, tools):
    identifiers = [identifiers] if isinstance(identifiers, str) else identifiers
    selected = [o for o in tools.offers if o['id'] in identifiers]
    if not selected or len(selected) != len(identifiers):
        clear_offers(tools)
        return unavailable()
    tools.offers, tools.goal = selected, selected[0].get('goal')
    teams = {team for o in selected for team in (o.get('goal') or {}).get('team_ids', ())}
    tools.answer_teams = teams if len(teams) == len(selected) else {None}
    return QuestionDraft(answer_kind='statistic',status='answer',selected_offer_id=selected[0]['id'],
                         statistic_request=draft.statistic_request,
                         text=' '.join(stat_answer(offer) for offer in selected),
                         evidence_ids=['offer:'+o['id'] for o in selected])


async def dismissals(tools, teams):
    """Who was sent off, from the snapshot's MA3 cards (outside SPADL; deterministic, no model)."""
    rows = [row for row in await tools.match_data.cards(tools.payload.snapshot) if row['colour'] in ('red', 'second_yellow')
            and (None in teams or not teams or row.get('team_id') in teams)]
    names = {p['id']: p['name'] for p in tools.payload.players}
    ids = [tools._event_reference(row)['evidence_id'] for row in rows]
    if not rows:
        return 'Nobody has been sent off.', ids
    return 'Sent off: ' + ', '.join(
        f"{names.get(row.get('player_id'), 'unknown player')} ({row['colour'].replace('_', ' ')}, "
        f"{minute_label(row['period'], row['match_time_seconds'])})" for row in rows) + '.', ids


async def resolve_answer(draft, tools):
    if draft.answer_kind == 'statistic' and SCORE.search(wording(draft, tools)) and hasattr(tools.match_data, 'score'):
        tools.score = await tools.match_data.score(tools.payload.snapshot, [t['id'] for t in tools.payload.teams])
    answer = await resolve_stat(draft, tools)
    if draft.answer_kind != 'statistic' or answer.status == 'clarification' or not SENT_OFF.search(wording(draft, tools)):
        return answer
    if answer.status == 'answer':
        note, ids = await dismissals(tools, getattr(tools, 'answer_teams', set()))
        tools.answer_text = ' '.join([tools.answer_text or answer.text, note])
        return answer.model_copy(update={'text': tools.answer_text, 'evidence_ids': [*answer.evidence_ids, *ids][:20]})
    # The count could not be read; who was sent off still can.
    note, ids = await dismissals(tools, set())
    return QuestionDraft(answer_kind='match', status='answer', text=note, evidence_ids=ids[:20])


async def resolve_stat(draft, tools):
    tools.answer_text = None
    if draft.status != 'answer' or draft.answer_kind != 'statistic':
        clear_offers(tools)
        return unavailable() if draft.status == 'unsupported' and draft.answer_kind == 'statistic' else draft
    if draft.selected_offer_id:
        # Prepared A is valid even if a later exploration of B failed or clarified.
        return selected_answer(draft,draft.selected_offer_id,tools)
    if draft.standard_stat_id:
        # The question agent's standard_stat route gets the planner's plain-'saves' guard too.
        stat_id = real_save_id(wording(draft, tools), draft.standard_stat_id, {s['id'] for s in tools.stats})
        return standard_answer(draft,next((s for s in tools.stats if s['id']==stat_id),None),tools)
    if draft.statistic_request:
        # Never treat a result for A as the answer to a final request for B.
        result = getattr(tools,'prepared_results',{}).get(draft.statistic_request)
        if result is None:
            result = await tools.prepare(draft.statistic_request)
    elif getattr(tools,'original_prompt',None):
        result = await tools.prepare_original()
    else:
        clear_offers(tools)
        return unavailable()
    if result['status']=='ranking':
        # A player leaderboard: deterministic text; the leaders are offered for tracking.
        answer = selected_answer(draft,result['offer_ids'],tools) if result['offer_ids'] else QuestionDraft(
            answer_kind='statistic',status='answer',statistic_request=draft.statistic_request,text=result['text'])
        if answer.status == 'answer':
            tools.answer_text = result['text']
            answer = answer.model_copy(update={'text': result['text']})
        return answer
    if result['status']=='ready':
        return selected_answer(draft,result.get('offer_ids') or [result.get('offer_id')],tools)
    if result['status']=='reuse':
        return standard_answer(draft,result.get('stats') or result.get('stat'),tools,result.get('formula'))
    clear_offers(tools)
    if result['status']=='clarification':
        clarification = result.get('clarification')
        if clarification:
            clarification = {key: clarification[key] for key in ('question', 'options', 'allow_free_text') if key in clarification}
        return QuestionDraft(answer_kind='statistic',status='clarification',text=result['message'],clarification=clarification)
    return unavailable(result.get('message'))
