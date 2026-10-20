"""Resolve the final declared source, never the last incidental tool invocation."""
from backend.models.questions import QuestionDraft
from backend.models.stat_offers import stat_answer
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
    kind = row['id'].split(':', 1)[-1]
    teams = [s for s in stats if s.get('team_id') and s['id'] == f"{s['team_id']}:{kind}"
             and s.get('available') and s.get('complete') and s.get('value') is not None]
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


def standard_answer(draft, row, tools):
    clear_offers(tools)
    if not row or not row.get('available') or not row.get('complete'):
        return unavailable(row and f"{row['label']} is not available in this recording.")
    rows = split_rows(row, tools.stats)
    tools.offers = [{'id': str(uuid4()), 'kind': 'standard', 'standard_stat_id': item['id'],
                     'label': item['label'], 'value': item['value'],
                     'unit': item.get('unit', ''),
                     'snapshot_id': tools.payload.snapshot.id, 'run_id': tools.payload.snapshot.run_id}
                    for item in rows]
    return QuestionDraft(answer_kind='statistic',status='answer',standard_stat_id=row['id'],
                         statistic_request=draft.statistic_request,
                         text=' '.join(stat_answer(offer) for offer in tools.offers),
                         evidence_ids=['stat:'+item['id'] for item in rows])


def selected_answer(draft, identifier, tools):
    selected = next((o for o in tools.offers if o['id']==identifier),None)
    if selected is None:
        clear_offers(tools)
        return unavailable()
    tools.offers, tools.goal = [selected], selected.get('goal')
    return QuestionDraft(answer_kind='statistic',status='answer',selected_offer_id=identifier,
                         statistic_request=draft.statistic_request,
                         text=stat_answer(selected),evidence_ids=['offer:'+identifier])


async def resolve_answer(draft, tools):
    if draft.status != 'answer' or draft.answer_kind != 'statistic':
        clear_offers(tools)
        return unavailable() if draft.status == 'unsupported' and draft.answer_kind == 'statistic' else draft
    if draft.selected_offer_id:
        # Prepared A is valid even if a later exploration of B failed or clarified.
        return selected_answer(draft,draft.selected_offer_id,tools)
    if draft.standard_stat_id:
        return standard_answer(draft,next((s for s in tools.stats if s['id']==draft.standard_stat_id),None),tools)
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
    if result['status']=='ready':
        return selected_answer(draft,result.get('offer_id'),tools)
    if result['status']=='reuse':
        return standard_answer(draft,result.get('stat'),tools)
    clear_offers(tools)
    if result['status']=='clarification':
        clarification = result.get('clarification')
        if clarification:
            clarification = {key: clarification[key] for key in ('question', 'options', 'allow_free_text') if key in clarification}
        return QuestionDraft(answer_kind='statistic',status='clarification',text=result['message'],clarification=clarification)
    return unavailable(result.get('message'))
