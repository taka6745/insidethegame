"""Resolve the final declared source, never the last incidental tool invocation."""
from backend.models.questions import QuestionDraft
from uuid import uuid4


def unavailable():
    return QuestionDraft(answer_kind='statistic',status='unsupported',
                         text='Sorry, I cannot answer that from the information available.')


def clear_offers(tools):
    tools.offers, tools.goal = [], None


def standard_answer(draft, row, tools):
    clear_offers(tools)
    if not row or not row.get('available') or not row.get('complete'):
        return unavailable()
    tools.offers = [{'id': str(uuid4()), 'kind': 'standard', 'standard_stat_id': row['id'],
                     'label': row['label'], 'value': row['value'],
                     'snapshot_id': tools.payload.snapshot.id, 'run_id': tools.payload.snapshot.run_id}]
    return QuestionDraft(answer_kind='statistic',status='answer',standard_stat_id=row['id'],
                         statistic_request=draft.statistic_request,
                         text=f"{row['label']}: {row['value']}.",evidence_ids=['stat:'+row['id']])


def selected_answer(draft, identifier, tools):
    selected = next((o for o in tools.offers if o['id']==identifier),None)
    if selected is None:
        clear_offers(tools)
        return unavailable()
    tools.offers, tools.goal = [selected], selected.get('goal')
    return QuestionDraft(answer_kind='statistic',status='answer',selected_offer_id=identifier,
                         statistic_request=draft.statistic_request,
                         text=f"{selected['label']}: {selected['value']}.",evidence_ids=['offer:'+identifier])


async def resolve_answer(draft, tools):
    if draft.status != 'answer' or draft.answer_kind != 'statistic':
        clear_offers(tools)
        return draft
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
        return QuestionDraft(answer_kind='statistic',status='clarification',text=result['message'])
    return unavailable()
