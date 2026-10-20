"""Shared demo checkpoints and read-only question history."""
from ..adapters.events import observed_events
from .recaps import build_recaps

AUTHORED = {'minute_recaps': 'minutes', 'tier_recaps': 'tiers', 'key_moments': 'key_moments', 'context': 'context'}


class NarrativeService:
    def __init__(self, repository, etl, audience, commentary):
        self.repository, self.etl, self.audience, self.commentary = repository, etl, audience, commentary

    async def capture(self, metadata, *, viewer):
        payload = await self.etl.read(metadata.snapshot.id)
        if payload.snapshot.model_dump(exclude={'captured_at'}) != metadata.snapshot.model_dump(exclude={'captured_at'}):
            raise ValueError('ETL checkpoint does not match the requested snapshot')
        payload.verify()
        events = observed_events(payload.events)
        try:
            document = self.repository.read(payload.snapshot.id)
        except KeyError:
            document = {'snapshot_id': payload.snapshot.id, 'match_id': payload.snapshot.match_id,
                        'complete': True, 'synthetic': True, 'recaps': build_recaps(payload, events),
                        # Authored neutral content is fixed at this snapshot, so later
                        # reads can never reveal anything past its observed position.
                        'authored': self.commentary.neutral(payload, events),
                        'items': [], 'events': events[-30:], 'audience_revision': None}
        if viewer:
            catalogue = await self.audience.read(payload.snapshot.match_id)
            document['items'] = self.commentary.read(payload, events, catalogue['generation_targets'])
            document['audience_revision'] = catalogue['revision']
        # Question capture only materializes factual neutral context. It cannot author
        # or publish bucket narratives, and never fetches viewer identities/catalogues.
        self.repository.save(payload.snapshot.id, payload.snapshot.run_id, document)
        return {'snapshot_id': payload.snapshot.id, 'synthetic': True}

    def read(self, snapshot_id, operation, offset=0, limit=100, ids=None, tier=None,
             start=None, end=None, period=None, **unused):
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError('Invalid page')
        document = self.repository.read(snapshot_id)
        result = {key: document[key] for key in ('snapshot_id', 'match_id', 'complete', 'synthetic')}
        if operation == 'viewer':
            result.update(items=document['items'], events=document['events'],
                          audience_revision=document['audience_revision'])
        elif operation == 'compact':
            result.update({key: value for key, value in document['recaps'].items() if key != 'archive'})
        elif operation == 'recaps':
            rows = [row for row in document['recaps']['archive'] if (not ids or row['id'] in ids)
                    and (not tier or row['tier'] == tier) and (period is None or row['period'] == period)
                    and (start is None or row['end_seconds'] > start) and (end is None or row['start_seconds'] < end)]
            result.update(items=rows[offset:offset + limit], has_more=offset + limit < len(rows))
        elif operation in AUTHORED:
            authored = document['authored']
            if operation == 'context':
                result.update(authored['context'])
            else:
                rows = [row for row in authored[AUTHORED[operation]] if (not ids or row['id'] in ids)
                        and (not tier or row.get('tier') == tier) and (period is None or row['period'] == period)]
                result.update(items=rows[offset:offset + limit], has_more=offset + limit < len(rows))
        else:
            raise ValueError('Unsupported narrative read')
        return result
