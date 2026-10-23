"""Generate backend/contracts/spadl-reference.json from etl/contracts/spadl-action.schema.json and the Opta source
of each type, result and body part probed from etl/reference/spadl.py. tests/test_spadl_contract.py fails when the
file is stale. Run `python -m devtools.spadl_reference` from user-backend/."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / 'etl' / 'contracts' / 'spadl-action.schema.json'
CODES = ROOT / 'etl' / 'contracts' / 'opta-codes.json'
CONVERTER = ROOT / 'etl' / 'reference' / 'spadl.py'
OUTPUT = Path(__file__).resolve().parents[1] / 'backend' / 'contracts' / 'spadl-reference.json'


def _converter():
    sys.path.insert(0, str(ROOT / 'etl'))
    from reference import spadl
    return spadl


def build():
    spadl = _converter()
    schema = json.loads(SCHEMA.read_text())
    codes = json.loads(CODES.read_text())
    props = schema['properties']
    constants = {value: name for name, value in vars(spadl).items()
                 if name.isupper() and isinstance(value, int) and not isinstance(value, bool) and 0 < value < 1000}
    type_name = lambda t: codes['eventTypes'].get(str(t)) or constants.get(t, f'type {t}').replace('_', ' ').capitalize()
    q_name = lambda q: codes['qualifiers'].get(str(q), f'qualifier {q}').split(' (')[0]
    source = CONVERTER.read_text()
    qualifiers = sorted({int(q) for q in re.findall(r'\b(\d+) in q\b', source)}
                        | {int(q) for group in re.findall(r'\(\(([\d, ]+)\)', source) for q in group.split(',') if q.strip()})
    opta_types = sorted(t for t in constants if t < 900 and t != spadl.BALL_RECOVERY)  # recoveries: see dribble

    found = {'types': {}, 'results': {}, 'bodyparts': {}}

    def note(kind, name, text):
        found[kind].setdefault(name, [])
        if text not in found[kind][name]:
            found[kind][name].append(text)

    type_quals = sorted({int(q) for q in re.findall(r'\b(\d+) in q\b', source[source.index('def _type'):source.index('def _result')])})
    probes = [()] + [(q,) for q in qualifiers] + [(a, b) for i, a in enumerate(type_quals) for b in type_quals[i + 1:]]
    label = lambda t, qs: f'Opta {t} {type_name(t)}' + ''.join(f' + {q_name(q)} (q{q})' for q in qs)
    def probe(t, outcome, quals):
        """(type, result) of one MA3 row through the whole converter, followed by a team-mate's pass."""
        row = lambda i, typ, out, q: {'id': i, 'typeId': typ, 'outcome': int(out), 'periodId': 1, 'timeMin': 0,
                                      'timeSec': i, 'contestantId': 'home', 'playerId': 'p', 'x': 50, 'y': 50,
                                      'eventSeq': i, 'qualifier': [{'qualifierId': k, 'value': v} for k, v in q.items()]}
        actions = spadl.convert([row(1, t, outcome, quals), row(2, spadl.PASS, 1, {})], 'home')
        first = [a for a in actions if a['seq'] == 1]
        return (first[0]['typeName'], first[0]['resultName']) if first else ('non_action', None)

    for t in opta_types:
        for qs in probes:
            quals = dict.fromkeys(qs, '1')
            got = {o: probe(t, o, quals) for o in (True, False)}
            plain = {o: probe(t, o, {}) for o in (True, False)}
            singles = [{o: probe(t, o, {q: '1'}) for o in (True, False)} for q in qs] if len(qs) == 2 else []
            for o in (True, False):
                kind, result = got[o]
                if kind == 'non_action' or (qs and got[o] == plain[o]) or any(single[o] == got[o] for single in singles):
                    continue  # No action, or these qualifiers change nothing a simpler probe did not.
                if not qs or kind != plain[o][0]:
                    note('types', kind, label(t, qs) + ('' if got[True][0] == got[False][0] else
                                                        ' outcome success' if o else ' outcome fail'))
                if not qs or result != plain[o][1]:
                    note('results', result, label(t, qs) + ('' if got[True][1] == got[False][1] else
                                                            ' outcome success' if o else ' outcome fail'))
        for q in qualifiers:
            part, observed = spadl._bodypart(t, {q: '1'})
            if observed:
                note('bodyparts', part, f'{q_name(q)} (q{q})')
    for part in schema['properties']['bodypartName']['enum']:
        if part not in found['bodyparts'] and part in ('foot', 'other'):
            found['bodyparts'][part] = []
    found['bodyparts'].setdefault('foot', []).append('default when no body-part qualifier (bodypartObserved false)')
    found['bodyparts'].setdefault('other', []).append('default for keeper actions without a qualifier')
    found['types'].setdefault('dribble', []).append(
        f'inserted by the converter: the same team moved the ball {spadl.MIN_DRIBBLE_LENGTH:g}-'
        f'{spadl.MAX_DRIBBLE_LENGTH:g} m within {spadl.MAX_DRIBBLE_DURATION:g} s between two actions, '
        f'or a ball recovery (Opta {spadl.BALL_RECOVERY}) moved it')

    zones = props['startZone']
    reference = {
        'about': 'GENERATED by user-backend/devtools/spadl_reference.py from etl/contracts/spadl-action.schema.json, '
                 'etl/contracts/opta-codes.json and etl/reference/spadl.py. Do not edit.',
        'sources': {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (SCHEMA, CODES, CONVERTER)},
        'description': schema['description'],
        'types': props['typeName']['enum'],
        'results': props['resultName']['enum'],
        'bodyparts': props['bodypartName']['enum'],
        'zones': zones['enum'],
        'families': {'pass': spadl.PASS_FAMILY, 'shot': spadl.SHOT_FAMILY},
        'field_meanings': {name: value.get('description', '') for name, value in props.items()},
        'opta': {kind: {name: found[kind].get(name, []) for name in props[field]['enum']}
                 for kind, field in (('types', 'typeName'), ('results', 'resultName'), ('bodyparts', 'bodypartName'))},
        'outside_spadl': schema['properties']['resultName'].get('description', ''),
    }
    return reference


def main():
    OUTPUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + '\n')
    print(OUTPUT)


if __name__ == '__main__':
    main()
