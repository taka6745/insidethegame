"""Bind reviewed prose to an exact canonical ETL export; never generate prose.

Input export: recording_hash, events (canonical), video_times, teams.
The caller must explicitly supply the hash reviewed while authoring the text.
"""
import argparse
import hashlib
import json
from pathlib import Path

STYLES = ('simple', 'casual', 'experienced', 'analytical')
PERSPECTIVES = ('home', 'away', 'neutral')
EVIDENCE_TYPES = {'shot', 'corner', 'foul', 'foul_won', 'offside', 'card',
                  'free_kick', 'throw_in', 'goal_kick', 'kick_off', 'penalty'}
ORDER = {
    'simple': ('goals', 'shots', 'possession', 'passes', 'pass_accuracy'),
    'casual': ('goals', 'shots', 'possession', 'passes', 'pass_accuracy'),
    'experienced': ('shots', 'possession', 'pass_accuracy', 'passes', 'goals'),
    'analytical': ('possession', 'pass_accuracy', 'shots', 'passes', 'goals'),
}


def bind(text, source, reviewed_hash):
    if source['recording_hash'] != reviewed_hash:
        raise ValueError('The reviewed recording hash must match the ETL export')
    if len(text['minutes']) != 12 or any(len(rows) != 12 for rows in text['minutes']):
        raise ValueError('Author exactly twelve bucket versions for each of twelve video minutes')
    events, times = source['events'], source['video_times']
    result = {'schema_version': 1, 'recording_hash': reviewed_hash,
              'provenance': text['provenance'], 'items': []}
    for minute, versions in enumerate(text['minutes'], 1):
        cursor = next((i + 1 for i, seconds in enumerate(times) if seconds >= minute * 60), len(events))
        prefix = events[:cursor]
        clock = 5400 if minute == 12 else prefix[-1]['match_time_seconds']
        digest = hashlib.sha256(json.dumps(prefix, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        # Return compact evidence references; the prefix digest guards all factual claims.
        evidence = [event for event, seconds in zip(events, times) if seconds <= minute * 60
                    and (event['event_type'] == 'goal' or
                         (seconds > (minute - 1) * 60 and event['event_type'] in EVIDENCE_TYPES))]
        if not evidence:
            evidence = prefix[-1:]
        for index, prose in enumerate(versions):
            perspective, style = PERSPECTIVES[index // 4], STYLES[index % 4]
            team_id = 'all' if perspective == 'neutral' else source['teams'][index // 4]['id']
            bucket = f'{perspective}:{style}'
            result['items'].append({'id': f'grf-minute-{minute}:{bucket}', 'bucket_id': bucket,
                'video_minute': minute, 'release_cursor': cursor, 'clock_seconds': clock,
                'period': 1 if minute <= 6 else 2, 'text': prose, 'evidence': evidence,
                'prefix_digest': digest, 'stat_ids': [f'{team_id}:{kind}' for kind in ORDER[style]]})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('canonical_export', type=Path)
    parser.add_argument('--reviewed-hash', required=True)
    parser.add_argument('--text', type=Path, default=Path('fixtures/commentary-text.json'))
    parser.add_argument('--output', type=Path, default=Path('fixtures/grf-narratives.json'))
    args = parser.parse_args()
    result = bind(json.loads(args.text.read_text()), json.loads(args.canonical_export.read_text()), args.reviewed_hash)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
