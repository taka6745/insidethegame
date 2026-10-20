"""Release authored demo content. Never generate or infer football claims.

A unit (minute, tier or key moment) is visible only when the snapshot has
observed its release cursor and clock, the recording hash matches, its
delivery prefix is unchanged and its evidence has no later correction.
"""
from pathlib import Path

from ..models.clock import position
from ..models.fixtures import KeyMoment, Minute, NarrativeFixture, Tier, prefix_digests

CONTEXT_TAIL = 100


class CommentaryFixture:
    def __init__(self, path):
        self.path = Path(path)
        self.document = NarrativeFixture.model_validate_json(self.path.read_text())

    def _intact(self, payload, observed):
        snapshot, fixture = payload.snapshot, self.document
        if fixture.recording_hash != snapshot.recording_hash:
            return []
        reached = (snapshot.period or 1, snapshot.clock_seconds or 0)
        units = [unit for unit in (*fixture.minutes, *fixture.tiers, *fixture.key_moments)
                 if unit.release.cursor <= snapshot.cursor
                 and (unit.release.period, unit.release.clock_seconds) <= reached]
        current = {event['event_id']: event for event in observed}
        deliveries = payload.events
        # Substitute current revisions in delivery order: any earlier correction
        # or deletion changes the digest of every prefix that contains it.
        digests = prefix_digests([current.get(event['event_id']) for event in deliveries],
                                 {unit.release.cursor for unit in units})
        # An event first delivered after a prefix but placed before its end would
        # rewrite that history; track the earliest such placement per cursor.
        first = {}
        for index, event in enumerate(deliveries):
            first.setdefault(event['event_id'], index)
        placed = {}
        for event in observed:
            placed.setdefault(first[event['event_id']], []).append(position(event))
        earliest = [None] * (len(deliveries) + 1)
        for index in range(len(deliveries) - 1, -1, -1):
            later = placed.get(index, []) + ([earliest[index + 1]] if earliest[index + 1] else [])
            earliest[index] = min(later, default=None)

        def unchanged(unit):
            cursor = unit.release.cursor
            if digests.get(cursor) != unit.release.prefix_digest:
                return False
            if earliest[cursor] is not None and earliest[cursor] < position(deliveries[cursor - 1]):
                return False
            return all(current.get(source['event_id']) == source for source in getattr(unit, 'evidence', ()))

        valid = {unit.id for unit in units if not isinstance(unit, Tier) and unchanged(unit)}
        # A tier also needs every child intact; children are never wider, so go narrow first.
        for tier in sorted((unit for unit in units if isinstance(unit, Tier)),
                           key=lambda row: (row.end_seconds - row.start_seconds, row.release.cursor)):
            if unchanged(tier) and all(child in valid for child in tier.child_ids):
                valid.add(tier.id)
        return [unit for unit in units if unit.id in valid]

    def read(self, payload, observed, targets):
        """Bucket narratives for enabled targets, unchanged authored text."""
        enabled = {target['bucket_id'] for target in targets}
        return [{'id': f'{minute.id}:{row.bucket_id}', 'text': row.text,
                 'clock_seconds': minute.release.clock_seconds, 'period': minute.period,
                 'buckets': [row.bucket_id], 'stat_ids': row.stat_ids, 'synthetic': True,
                 'evidence_ids': [source['event_id'] for source in minute.evidence]}
                for minute in self._intact(payload, observed) if isinstance(minute, Minute)
                for row in minute.narratives if row.bucket_id in enabled]

    def neutral(self, payload, observed):
        """Minute recaps, tier recaps, re-ranked key moments and the context view."""
        units = self._intact(payload, observed)
        minutes = [{'id': unit.id, 'period': unit.period, 'minute': unit.minute, 'label': unit.label,
                    'start_seconds': unit.start_seconds, 'end_seconds': unit.end_seconds, 'tier': 'minute',
                    'summary': unit.recap, 'video_seconds': unit.release.video_seconds,
                    'evidence_ids': [source['event_id'] for source in unit.evidence]}
                   for unit in units if isinstance(unit, Minute)]
        tiers = [{'id': unit.id, 'tier': unit.tier, 'period': unit.period, 'start_seconds': unit.start_seconds,
                  'end_seconds': unit.end_seconds, 'child_ids': unit.child_ids, 'summary': unit.summary,
                  'video_seconds': unit.release.video_seconds}
                 for unit in units if isinstance(unit, Tier)]
        moments = sorted((unit for unit in units if isinstance(unit, KeyMoment)), key=lambda row: row.rank)
        # Global ranks would reveal how many bigger moments are still to come.
        moments = [{'id': unit.id, 'rank': rank, 'title': unit.title, 'summary': unit.summary,
                    'event_ids': unit.event_ids, 'period': unit.period, 'minute': unit.minute, 'label': unit.label,
                    'start_video_seconds': unit.start_video_seconds, 'end_video_seconds': unit.end_video_seconds}
                   for rank, unit in enumerate(moments, 1)]
        for rows in (minutes, tiers):
            rows.sort(key=lambda row: (row['period'], row['start_seconds'], -row['end_seconds']))
        return {'minutes': minutes, 'tiers': tiers, 'key_moments': moments,
                'context': context(minutes, tiers, observed)}


def context(minutes, tiers, observed):
    """Context-builder view: broadest released blocks, then facts since they end."""
    covered = {child for tier in tiers for child in tier['child_ids']}
    blocks = sorted((row for row in (*minutes, *tiers) if row['id'] not in covered),
                    key=lambda row: (row['period'], row['start_seconds']))
    since = (blocks[-1]['period'], blocks[-1]['end_seconds']) if blocks else (0, 0)
    tail = [event for event in observed if position(event) >= since and event['event_type'] != 'touch']
    return {'blocks': blocks, 'tail': tail[-CONTEXT_TAIL:], 'tail_truncated': len(tail) > CONTEXT_TAIL,
            'key_events': [event for event in observed if event['event_type'] in ('goal', 'card', 'penalty')]}
