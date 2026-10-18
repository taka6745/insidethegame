"""Bounded, development-only snapshot bridge for separate fake upstream services."""
import hashlib
import json
from collections import OrderedDict
from fastapi import HTTPException
from .models.questions import SnapshotInput
from .fake_recaps import build_recaps
from .fake_product_narratives import viewer_narratives


def snapshot_id(payload):
    data = payload.model_dump(mode='json')
    data['snapshot'].pop('id', None)
    data['snapshot'].pop('captured_at', None)
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def observed_events(deliveries):
    latest = {}
    for event in deliveries:
        previous = latest.get(event.event_id)
        if previous is None or event.revision > previous.revision:
            latest[event.event_id] = event
    return sorted((e for e in latest.values() if not e.deleted), key=lambda e: (e.match_time_seconds, e.event_id))


def standard_stats(payload, events):
    results = []
    for team in [None, *payload.teams]:
        selected = [e for e in events if team is None or e.team_id == team['id']]
        for kind, types in [('shots', ('shot', 'goal')), ('goals', ('goal',)), ('cards', ('card',)), ('corners', ('corner',)), ('passes', ('pass',))]:
            identifier = f"{team['id'] if team else 'all'}:{kind}"
            results.append({'id': identifier, 'label': f"{team['name'] if team else 'Both teams'} {kind}",
                            'value': sum(e.event_type in types for e in selected), 'available': True,
                            'team_id': team['id'] if team else None,
                            'definition': f"Count {', '.join(types)} events for the whole match observed so far.",
                            'event_types': list(types), 'complete': True})
    return results


class FakeQuestionData:
    def __init__(self, role):
        self.role, self.snapshots = role, OrderedDict()
        self.viewer_snapshots = OrderedDict()

    def store(self, payload: SnapshotInput):
        return self._store(payload, self.snapshots, 16)

    def store_viewer(self, payload: SnapshotInput):
        return self._store(payload, self.viewer_snapshots, 2)

    def _store(self, payload, destination, capacity):
        if payload.snapshot.cursor != len(payload.events) or any(e.match_id != payload.snapshot.match_id for e in payload.events):
            raise HTTPException(422, 'Snapshot deliveries must match its identity and cursor')
        if snapshot_id(payload) != payload.snapshot.id:
            raise HTTPException(422, 'Snapshot content does not match its ID')
        destination[payload.snapshot.id] = payload
        destination.move_to_end(payload.snapshot.id)
        while len(destination) > capacity:
            destination.popitem(last=False)
        return {'snapshot_id': payload.snapshot.id, 'synthetic': True}

    def read(self, root, info, snapshotId, operation, offset=0, limit=100, ids=None, tier=None, start=None, end=None, eventType=None, playerId=None, period=None):
        payload = self.snapshots.get(snapshotId) or self.viewer_snapshots.get(snapshotId)
        if payload is None:
            raise ValueError('Snapshot unavailable; capture it again')
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError('Invalid page')
        events = observed_events(payload.events)
        result = {'snapshot_id': snapshotId, 'match_id': payload.snapshot.match_id, 'complete': True, 'synthetic': True}
        if self.role == 'etl' and operation == 'stats':
            result['stats'] = standard_stats(payload, events)
        elif self.role == 'etl' and operation == 'events':
            rows = [e.model_dump() for e in events if (start is None or e.match_time_seconds >= start)
                    and (end is None or e.match_time_seconds < end)
                    and (eventType is None or e.event_type == eventType) and (playerId is None or e.player_id == playerId)
                    and (period is None or e.period == period)]
            result.update(items=rows[offset:offset + limit], has_more=offset + limit < len(rows), total=len(rows))
        elif self.role == 'narrative' and operation == 'viewer':
            result.update(viewer_narratives(payload, events))
        elif self.role == 'narrative' and operation in ('compact', 'recaps'):
            recaps = build_recaps(payload, events)
            if operation == 'compact':
                recaps.pop('archive')
                result.update(recaps)
            else:
                rows = [r for r in recaps['archive'] if (not ids or r['id'] in ids)
                        and (not tier or r['tier'] == tier) and (start is None or r['end_seconds'] > start)
                        and (end is None or r['start_seconds'] < end)]
                result.update(items=rows[offset:offset + limit], has_more=offset + limit < len(rows))
        else:
            raise ValueError('Unsupported snapshot read')
        return result

    def wire(self, app, schema):
        app.post('/dev/question-snapshots')(self.store)
        app.post('/dev/viewer-snapshots')(self.store_viewer)
        schema.query_type.fields['questionData'].resolve = self.read
