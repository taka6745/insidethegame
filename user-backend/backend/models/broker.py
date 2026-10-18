"""Versioned broker wire contracts, independent of SDK message objects."""
from typing import Literal
from pydantic import Field
from .questions import Strict, MatchSnapshot, SnapshotInput
from .events import Event


class MatchDelivery(Strict):
    type: Literal['MatchEvent']
    version: Literal[1]
    snapshot: SnapshotInput
    event: Event | None


class BucketItem(Strict):
    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=3000)
    clock_seconds: int = Field(ge=0)
    period: int
    buckets: list[str] = Field(max_length=48)
    stat_ids: list[str] = Field(max_length=30)
    synthetic: Literal[True]
    evidence_ids: list[str] = Field(max_length=200)


class BucketDelivery(Strict):
    type: Literal['BucketNarratives']
    version: Literal[1]
    snapshot: MatchSnapshot
    items: list[BucketItem] = Field(max_length=480)
    events: list[Event] = Field(max_length=30)
    audience_revision: int = Field(ge=1)

    def document(self):
        return {'snapshot_id': self.snapshot.id, 'match_id': self.snapshot.match_id,
                'complete': True, 'synthetic': True, 'audience_revision': self.audience_revision,
                'items': [item.model_dump() for item in self.items],
                'events': [event.model_dump() for event in self.events]}
