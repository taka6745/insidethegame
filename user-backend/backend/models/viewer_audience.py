"""Match-local viewer selection: one of the match's enabled buckets; separate from account defaults."""
from backend.models.audiences import BucketId, StrictModel


class ViewerAudience(StrictModel):
    bucket_id: BucketId


def option_label(option, teams):
    """An option's viewer label with `{home}`/`{away}` resolved from the match's teams."""
    label = option.get('label') or option['id'].replace('_', ' ').capitalize()
    for team in teams:
        label = label.replace('{%s}' % team.get('position'), team['name'])
    return label


def supported_side(layers, selections):
    """`home`/`away` when a selected option backs a team: its `team`, else a label naming only `{home}` or
    `{away}` (as the narrative engine reads it); layer ids carry no meaning."""
    for layer in layers:
        option = next((o for o in layer['options'] if o['id'] == selections.get(layer['id'])), None)
        if option is None:
            continue
        if option.get('team') in ('home', 'away'):
            return option['team']
        sides = [s for s in ('home', 'away') if '{%s}' % s in (option.get('label') or '')]
        if len(sides) == 1:
            return sides[0]
    return None


def bucket_label(layers, selections, teams):
    """`Riverton Rovers · Analytical`: each layer's chosen option label, in layer order, without options kept out of it."""
    chosen = (next(o for o in layer['options'] if o['id'] == selections[layer['id']]) for layer in layers)
    return ' · '.join(option_label(option, teams) for option in chosen if option.get('in_label') is not False)
