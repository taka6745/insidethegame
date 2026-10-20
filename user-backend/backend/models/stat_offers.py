"""Stable pin identity for ETL stats and shared custom calculations."""
from .rules import Rule


def stat_answer(offer):
    """Keep ETL measurement units when rendering a deterministic answer."""
    suffix = '%' if offer.get('unit') == '%' else ''
    return f"{offer['label']}: {offer['value']}{suffix}."


def pin_id(offer):
    if offer.get('kind') == 'standard':
        return 'standard:' + offer['standard_stat_id']
    return Rule.model_validate(offer['rule']).calculation_id
