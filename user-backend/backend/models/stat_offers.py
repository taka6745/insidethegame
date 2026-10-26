"""Stable pin identity for ETL stats and shared custom calculations."""
from backend.models.rules import Rule
import hashlib
from uuid import uuid4


def comparison_offer(offers, label, teams, goal=None):
    names = {team['id']: team['name'] for team in teams}
    return {'id': str(uuid4()), 'kind': 'comparison', 'label': label[:160], 'value': None,
            'unit': offers[0].get('unit', ''), 'goal': goal,
            'snapshot_id': offers[0]['snapshot_id'], 'match_id': offers[0]['match_id'],
            'sides': [{key: side[key] for key in ('kind', 'standard_stat_id', 'rule', 'label', 'value', 'unit', 'team_id')
                       if key in side} | {'name': names[side['team_id']]} for side in offers]}


def stat_answer(offer):
    """Keep ETL measurement units when rendering a deterministic answer."""
    if offer.get('sides'):
        return ' '.join(stat_answer(side) for side in offer['sides'])
    unit = offer.get('unit', '')
    suffix = '%' if unit == '%' else (' ' + unit if unit else '')
    value = offer['value']
    if value is None:
        return f"{offer['label']}: not available yet. You can track it as events arrive."
    value = format(value, '.1f').rstrip('0').rstrip('.') if isinstance(value, float) else str(value)
    return f"{offer['label']}: {value}{suffix}."


def pin_id(offer):
    if offer.get('kind') == 'comparison':
        members = '|'.join(sorted(pin_id(side) for side in offer['sides']))
        return 'comparison:' + hashlib.sha256(members.encode()).hexdigest()[:24]
    if offer.get('kind') == 'standard':
        return 'standard:' + offer['standard_stat_id']
    return Rule.model_validate(offer['rule']).calculation_id


def viewer_pin_id(offer, match_id):
    """A pin's id in a viewer's cards: `pin_id`, suffixed with the source match when the offer came from another live
    match (two matches' possession stats are different pins)."""
    source = offer.get('match_id')
    return pin_id(offer) if source in (None, match_id) else f'{pin_id(offer)}@{source}'


def split_pin_id(identifier):
    """(calculation or stat pin id, source match id or None)."""
    base, _, source = identifier.partition('@')
    return base, source or None
