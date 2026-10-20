"""Stable pin identity for ETL stats and shared custom calculations."""
from .rules import Rule


def stat_answer(offer):
    """Keep ETL measurement units when rendering a deterministic answer."""
    unit = offer.get('unit', '')
    suffix = '%' if unit == '%' else (' ' + unit if unit else '')
    value = offer['value']
    if value is None:
        return f"{offer['label']}: not available yet. You can track it as events arrive."
    value = format(value, '.1f').rstrip('0').rstrip('.') if isinstance(value, float) else str(value)
    return f"{offer['label']}: {value}{suffix}."


def pin_id(offer):
    if offer.get('kind') == 'standard':
        return 'standard:' + offer['standard_stat_id']
    return Rule.model_validate(offer['rule']).calculation_id
