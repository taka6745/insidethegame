"""Bind reviewed prose to an exact canonical ETL export; never generate prose.

Input export: recording_hash, events (canonical, delivery order), video_times, teams.
Authored text: provenance, minutes {id: {recap, narratives {bucket: text}}}, tiers, key_moments
(see fixtures/README.md). The caller must supply the hash reviewed while authoring.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from commentary_schema import (BUCKETS, PERIOD_START_SECONDS, NarrativeFixture, minute_id, minute_label,  # noqa: E402
                               position, prefix_digests)

EVIDENCE_TYPES = {'shot', 'save', 'corner', 'corner_awarded', 'foul', 'foul_won', 'offside', 'card',
                  'free_kick', 'penalty', 'error', 'kick_off', 'period_start', 'period_end'}
ORDER = {
    'simple': ('goals', 'shots', 'possession', 'passes', 'pass_accuracy'),
    'casual': ('goals', 'shots', 'possession', 'passes', 'pass_accuracy'),
    'experienced': ('shots', 'possession', 'pass_accuracy', 'passes', 'goals'),
    'analytical': ('possession', 'pass_accuracy', 'shots', 'passes', 'goals'),
}


def match_minutes(events):
    """Every broadcast minute of every period, stoppage included, empty minutes too."""
    last = {}
    for event in events:
        period, seconds = position(event)
        # A period ending exactly on a minute boundary does not open another minute.
        minute = seconds // 60 + (0 if event['event_type'] == 'period_end' and seconds % 60 == 0 else 1)
        last[period] = max(last.get(period, 0), minute)
    return [(period, minute) for period in sorted(last)
            for minute in range(PERIOD_START_SECONDS.get(period, 0) // 60 + 1, last[period] + 1)]


def closing_index(events, period, minute):
    """First delivery that proves the minute is over: later clock, later period or period end."""
    for index, event in enumerate(events):
        if position(event) >= (period, minute * 60) or (
                position(event)[0] == period and event['event_type'] == 'period_end'):
            return index
    raise ValueError(f'{minute_id(period, minute)} never closes; the export needs its period_end')


def bind(text, source, reviewed_hash):
    if source['recording_hash'] != reviewed_hash:
        raise ValueError('The reviewed recording hash must match the ETL export')
    events, times = source['events'], source['video_times']
    if len(times) != len(events) or any(b < a for a, b in zip(times, times[1:])):
        raise ValueError('video_times must align with events and never decrease')
    keys = match_minutes(events)
    if set(text['minutes']) != {minute_id(*key) for key in keys}:
        raise ValueError(f'Author exactly these minutes: {[minute_id(*key) for key in keys]}')

    def release(index):
        return {'cursor': index + 1, 'period': position(events[index])[0],
                'clock_seconds': events[index]['match_time_seconds'], 'video_seconds': times[index]}

    first = {}
    for index, event in enumerate(events):
        first.setdefault(event['event_id'], index)
    moment_index = {}
    for row in text.get('key_moments', []):
        missing = [identifier for identifier in row['event_ids'] if identifier not in first]
        if missing:
            raise ValueError(f'Key moment {row["id"]} cites unknown events {missing}')
        # Release only after the clip's events and its end have both been observed.
        watched = next((i for i, seconds in enumerate(times) if seconds >= row['end_video_seconds']), len(events) - 1)
        moment_index[row['id']] = max(max(first[i] for i in row['event_ids']), watched)

    closing = {key: closing_index(events, *key) for key in keys}
    digests = prefix_digests(events, {index + 1 for index in (*closing.values(), *moment_index.values())})
    teams = [team['id'] for team in source['teams']]
    minutes, units = [], {}
    for period, minute in keys:
        identifier, index = minute_id(period, minute), closing[(period, minute)]
        authored = text['minutes'][identifier]
        if set(authored['narratives']) != set(BUCKETS):
            raise ValueError(f'{identifier} needs exactly the twelve canonical bucket versions')
        prefix = events[:index + 1]
        inside = [position(event)[0] == period and (minute - 1) * 60 <= event['match_time_seconds'] < minute * 60
                  for event in prefix]
        # Compact evidence references; the prefix digest guards all factual claims.
        evidence = [event for event, here in zip(prefix, inside) if event['event_type'] == 'goal'
                    or (here and event['event_type'] in EVIDENCE_TYPES)]
        evidence = evidence or ([event for event, here in zip(prefix, inside) if here] or prefix)[-1:]
        narratives = []
        for bucket in BUCKETS:
            perspective, style = bucket.split(':')
            team = 'all' if perspective == 'neutral' else teams[('home', 'away').index(perspective)]
            narratives.append({'bucket_id': bucket, 'text': authored['narratives'][bucket],
                               'stat_ids': [f'{team}:{kind}' for kind in ORDER[style]]})
        row = {'id': identifier, 'period': period, 'minute': minute, 'label': minute_label(period, minute),
               'start_seconds': (minute - 1) * 60, 'end_seconds': minute * 60,
               'release': {**release(index), 'prefix_digest': digests[index + 1]},
               'evidence': evidence, 'recap': authored['recap'], 'narratives': narratives}
        minutes.append(row)
        units[identifier] = row

    tiers = []
    for authored in text.get('tiers', []):
        children = [units.get(child) for child in authored['child_ids']]
        if None in children:
            raise ValueError(f'Tier {authored["id"]} must list existing minutes or earlier tiers')
        row = {**authored, 'period': children[0]['period'], 'start_seconds': children[0]['start_seconds'],
               'end_seconds': children[-1]['end_seconds'],
               'release': max((child['release'] for child in children), key=lambda value: value['cursor'])}
        tiers.append(row)
        units[row['id']] = row

    moments = []
    for authored in text.get('key_moments', []):
        index = moment_index[authored['id']]
        evidence = [events[first[identifier]] for identifier in authored['event_ids']]
        period, seconds = position(evidence[0])
        moments.append({**authored, 'period': period, 'minute': seconds // 60 + 1,
                        'label': minute_label(period, seconds // 60 + 1), 'evidence': evidence,
                        'release': {**release(index), 'prefix_digest': digests[index + 1]}})

    fixture = NarrativeFixture.model_validate({
        'schema_version': 2, 'recording_hash': reviewed_hash, 'synthetic': True,
        'provenance': text['provenance'], 'minutes': minutes, 'tiers': tiers, 'key_moments': moments})
    return fixture.model_dump(mode='json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('canonical_export', type=Path)
    parser.add_argument('--reviewed-hash', required=True)
    parser.add_argument('--text', type=Path, default=Path('fixtures/commentary-text.json'))
    parser.add_argument('--output', type=Path, default=Path('fixtures/grf-narratives.json'))
    args = parser.parse_args()
    result = bind(json.loads(args.text.read_text()), json.loads(args.canonical_export.read_text()), args.reviewed_hash)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
