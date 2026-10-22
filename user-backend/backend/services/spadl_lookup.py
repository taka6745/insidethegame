"""lookup_spadl(term): one SPADL term's definition, Opta source, catalogue stats and a goal example.

Backed by the generated contract (backend/contracts/spadl-reference.json), the SPADL profile and the
live catalogue rows (ETL statDefinitions as served by statsAtSeq); nothing per term is hand-written.
Each answer is capped, and no match data is returned."""
import json
import re

from backend.adapters.feed_reference import reference
from backend.models.actions import SPADL

MAX_CHARS = 1200  # About 300 tokens.
GOAL_FIELDS = {'types': 'action_types', 'results': 'results', 'bodyparts': 'bodyparts', 'zones': 'end_zones'}
KINDS = {'types': 'events', 'results': 'results', 'bodyparts': 'bodyparts', 'zones': 'zones'}


def _normal(term):
    return re.sub(r'[\s-]+', '_', str(term or '').strip().lower())[:60]


def _stats(stats, test):
    kinds = {}
    for row in stats:
        kind = row['id'].split(':', 1)[-1]
        if kind not in kinds and test(row):
            kinds[kind] = row.get('definition', '')
    return [f'{kind}: {text}'[:160] for kind, text in kinds.items()][:6]


def _capped(answer):
    text = json.dumps(answer, ensure_ascii=False)
    while len(text) > MAX_CHARS:
        longest = max((k for k, v in answer.items() if isinstance(v, list) and v), key=lambda k: len(answer[k]), default=None)
        if longest is None:
            answer['definition'] = answer.get('definition', '')[:300]
            break
        answer[longest] = answer[longest][:-1]
        text = json.dumps(answer, ensure_ascii=False)
    return answer


def lookup(term, stats=()):
    """`term`: a SPADL type, result, body part, zone, catalogue stat id or kind, family or field name."""
    data, key = reference(), _normal(term)
    for kind, section in KINDS.items():
        if key in SPADL[kind]:
            field = GOAL_FIELDS[kind]
            used = {'types': lambda r: key in (r.get('action_types') or []),
                    'zones': lambda r: key in r.get('definition', '') or (key == 'opp_box' and 'box' in r['id'])
                    or (key == 'final_third' and 'final_third' in r['id'])}.get(kind, lambda r: key in r.get('definition', ''))
            answer = {'term': key, 'kind': kind[:-1], 'definition': data[section][key],
                      'opta_source': SPADL.get('opta', {}).get(kind, {}).get(key, []),
                      'catalogue_stats': _stats(stats, used),
                      'goal_example': {field: [key]} if kind != 'zones' else
                          {'end_zones': [key], 'note': 'or start_zones for where actions begin'}}
            return _capped(answer)
    kinds = {row['id'].split(':', 1)[-1]: row for row in stats}
    stat = next((row for row in stats if row['id'] == key), None) or kinds.get(key)
    if stat:
        types = stat.get('action_types') or []
        return _capped({'term': key, 'kind': 'catalogue_stat', 'definition': stat.get('definition', ''),
                        'action_types': types, 'available': stat.get('available', True),
                        'ids': [r['id'] for r in stats if r['id'].endswith(':' + stat['id'].split(':', 1)[-1])],
                        'use': 'reuse this stat id when it answers the whole request'})
    for name, text in data['families'].items():
        if key in (name, name.rstrip('s')):
            return _capped({'term': name, 'kind': 'family', 'definition': text,
                            'catalogue_stats': _stats(stats, lambda r: r['id'].endswith(':' + name))})
    fields = {**data['fields'], **data['derived']}
    if key in fields:
        return _capped({'term': key, 'kind': 'field', 'definition': fields[key]})
    close = [name for kind in KINDS for name in SPADL[kind] if key and (key in name or name in key)][:8]
    return {'term': key, 'unknown': True, 'close_matches': close,
            'known': {kind: list(SPADL[kind]) for kind in KINDS}}
