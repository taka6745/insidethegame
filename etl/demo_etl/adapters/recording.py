"""Only this boundary knows the synthetic Opta-inspired recording keys."""
import hashlib
import json
import math
from pathlib import Path
from demo_etl.models.snapshot import Event

MAX_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 100000


def adapt_event(raw):
    qualifiers = {q['type']: q['value'] for q in raw.get('qualifiers', [])}
    if len(qualifiers) != len(raw.get('qualifiers', [])):
        raise ValueError('Duplicate qualifiers')
    if raw.get('synthetic', True) is not True:
        raise ValueError('Demo adapter requires synthetic events')
    return Event(event_id=raw['eventId'], match_id=raw['matchId'], revision=raw.get('revision', 1),
        event_type=raw['typeName'], team_id=raw.get('teamId'), player_id=raw.get('playerId'),
        body_part=qualifiers.get('bodyPart'), period=raw['periodId'],
        match_time_seconds=raw['timeMin'] * 60 + raw['timeSec'], outcome=raw.get('outcome'),
        distance_metres=qualifiers.get('distanceMetres'), deleted=raw.get('deleted', False),
        sequence=raw.get('sequence'), video_seconds=raw.get('videoSeconds'), x=raw.get('x'), y=raw.get('y'),
        possession_id=raw.get('possessionId'), qualifiers=qualifiers)


class RecordingSource:
    def __init__(self, path):
        self.content = Path(path).read_bytes()
        if len(self.content) > MAX_BYTES:
            raise ValueError('Demo recording exceeds 16 MiB')
        self.fingerprint = hashlib.sha256(self.content).hexdigest()
        self.document = json.loads(self.content)
        if self.document.get('synthetic') is not True:
            raise ValueError('Demo recording must declare synthetic provenance')
        self.events = tuple(adapt_event(row) for row in self.document['events'])
        teams = {row['id'] for row in self.document['teams']}
        players = {row['id'] for row in self.document['players']}
        if len(teams) != 2 or not 0 < len(self.events) <= MAX_EVENTS:
            raise ValueError(f'Expected two teams and 1–{MAX_EVENTS} deliveries')
        if any(e.match_id != self.document['match_id'] or e.team_id is not None and e.team_id not in teams
               or e.player_id is not None and e.player_id not in players for e in self.events):
            raise ValueError('Unknown recording participant or match')
        for sample in self.document.get('possession_samples', []):
            if sample['team_id'] not in teams or any(not isinstance(sample[key], (int,float))
                or not math.isfinite(sample[key]) or sample[key] < 0 for key in ('video_seconds','duration_seconds')):
                raise ValueError('Invalid measured possession sample')

    def materialise(self, payload):
        if payload.snapshot.recording_hash != self.fingerprint or payload.snapshot.match_id != self.document['match_id']:
            raise ValueError('Recording identity changed; load the current ETL recording')
        if payload.snapshot.cursor > len(self.events):
            raise ValueError('Cursor exceeds the recording')
        if payload.teams != self.document['teams'] or payload.players != self.document['players']:
            raise ValueError('Recording catalogue mismatch')
        expected = self.events[:payload.snapshot.cursor]
        if payload.events and tuple(payload.events) != expected:
            raise ValueError('Consumer cannot replace ETL-owned events')
        # Broadcast clock: first-half stoppage can pass 45:00, so compare (period, time), never seconds alone.
        latest = max(expected, key=lambda e: (e.period, e.match_time_seconds), default=None)
        clock = (payload.snapshot.period, payload.snapshot.clock_seconds)
        expected_clock = (latest.period, latest.match_time_seconds) if latest else (None, None)
        # Finished means fully released; the producer may then declare its own final-whistle clock.
        finished = (payload.snapshot.cursor == len(self.events) and None not in clock
                    and clock[0] >= expected_clock[0])
        if clock != expected_clock and not finished:
            raise ValueError('Clock does not match the observed recording prefix')
        return payload.model_copy(update={'events': list(expected)})

    def possession(self, cursor):
        if not cursor:
            return {}
        video_time = max(row.get('videoSeconds', 0) for row in self.document['events'][:cursor])
        playback = self.document.get('playback', {})
        if cursor == len(self.events):
            video_time = playback.get('duration_seconds', video_time)
        totals = {}
        for sample in self.document.get('possession_samples', []):
            if sample['video_seconds'] <= video_time:
                team = sample['team_id']
                totals[team] = totals.get(team, 0) + sample['duration_seconds']
        return totals
