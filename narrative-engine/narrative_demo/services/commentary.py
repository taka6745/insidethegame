"""Read authored demo commentary. Never generate or infer football claims."""
import hashlib
import json
from pathlib import Path


class CommentaryFixture:
    def __init__(self, path):
        self.path = Path(path)
        self.document = json.loads(self.path.read_text())

    def read(self, payload, observed, targets):
        if self.document['recording_hash'] != payload.snapshot.recording_hash:
            return []
        enabled = {target['bucket_id'] for target in targets}
        current = {event['event_id']: event for event in observed}
        result = []
        prefix_matches = {}
        for row in self.document['items']:
            if (row['bucket_id'] not in enabled or row['release_cursor'] > payload.snapshot.cursor
                    or row['clock_seconds'] > (payload.snapshot.clock_seconds or 0)):
                continue
            if row.get('prefix_digest'):
                cursor = row['release_cursor']
                if cursor not in prefix_matches:
                    prefix = payload.events[:cursor]
                    ids = {event['event_id'] for event in prefix}
                    # Preserve delivery order but substitute current revisions. This
                    # invalidates commentary when any earlier factual input changes.
                    revised = [current.get(event['event_id']) for event in prefix]
                    unexpected = any(event['event_id'] not in ids and
                                     event['match_time_seconds'] < prefix[-1]['match_time_seconds']
                                     for event in observed)
                    digest = hashlib.sha256(json.dumps(revised, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                    prefix_matches[cursor] = (digest, unexpected)
                digest, unexpected = prefix_matches[cursor]
                if unexpected or digest != row['prefix_digest']:
                    continue
            # An amended/deleted source invalidates its authored interpretation.
            if any(current.get(source['event_id']) != source for source in row['evidence']):
                continue
            if not row['evidence']:
                continue
            result.append({'id': row['id'], 'text': row['text'], 'clock_seconds': row['clock_seconds'],
                           'period': row['period'], 'buckets': [row['bucket_id']],
                           'stat_ids': row['stat_ids'], 'synthetic': True,
                           'evidence_ids': [source['event_id'] for source in row['evidence']]})
        return result
