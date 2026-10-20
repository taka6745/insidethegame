"""Publish both stores before acknowledging an immutable snapshot."""
import threading

from demo_etl.services.statistics import observed, project


class MatchService:
    def __init__(self, history, stats, recording=None):
        self.history, self.stats, self.recording = history, stats, recording
        self._payloads = {}  # Published snapshots are immutable; keep the latest few parsed.
        self._lock = threading.Lock()  # Sync HTTP handlers share the cache across threads.

    def publish(self, payload, *, owned=False):
        if owned:
            if self.recording is None:
                raise ValueError('No demo recording configured')
            payload = self.recording.materialise(payload)
        payload.validate_identity()
        # Validate corrections before either store is changed.
        observed(payload.events)
        try:
            self.stats.read(payload.snapshot.id)
            self.history.metadata(payload.snapshot.id)
            return {'snapshot_id': payload.snapshot.id, 'synthetic': True}
        except KeyError:
            pass
        self.history.save(payload)
        possession = self.recording.possession(payload.snapshot.cursor) if owned else None
        self.stats.save(payload.snapshot.id, payload.snapshot.match_id, project(payload, possession, self.recording.document.get('capabilities') if owned else None))
        return {'snapshot_id': payload.snapshot.id, 'synthetic': True}

    def payload(self, snapshot_id):
        # A half-published history record must never appear ready to downstream readers.
        self.stats.read(snapshot_id)
        with self._lock:
            cached = self._payloads.get(snapshot_id)
        if cached is None:
            cached = self.history.read(snapshot_id)
            with self._lock:
                self._payloads[snapshot_id] = cached
                while len(self._payloads) > 8:
                    self._payloads.pop(next(iter(self._payloads)))
        return cached

    def read(self, snapshot_id, operation, *, offset=0, limit=100, start=None, end=None, eventType=None, playerId=None, period=None, **unused):
        if offset is None: offset = 0
        if limit is None: limit = 100
        if offset < 0 or not 1 <= limit <= (1000 if operation == 'events' else 100):
            raise ValueError('Invalid page')
        metadata = self.history.metadata(snapshot_id)
        result = {'snapshot_id':snapshot_id,'match_id':metadata['snapshot']['match_id'],'complete':True,'synthetic':True}
        if operation == 'stats':
            result['stats'] = self.stats.read(snapshot_id)
        elif operation == 'events':
            payload = self.payload(snapshot_id)
            rows = [e.model_dump(mode='json') for e in observed(payload.events)
                    if (start is None or e.match_time_seconds >= start) and (end is None or e.match_time_seconds < end)
                    and (eventType is None or e.event_type == eventType) and (playerId is None or e.player_id == playerId)
                    and (period is None or e.period == period)]
            result.update(items=rows[offset:offset+limit],has_more=offset+limit<len(rows),total=len(rows))
        else:
            raise ValueError('Unsupported ETL operation')
        return result
