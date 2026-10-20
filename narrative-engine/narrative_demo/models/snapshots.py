"""Demo checkpoint contract, independent of the user backend package."""
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from .clock import position


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    match_id: str = Field(min_length=1, max_length=128)
    recording_hash: str = Field(min_length=1, max_length=128)
    cursor: int = Field(ge=0, le=100000)
    clock_seconds: int | None = Field(default=None, ge=0)
    period: int | None = None
    captured_at: str


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot: Checkpoint
    events: list[dict] = Field(default_factory=list, max_length=100000)
    teams: list[dict] = Field(max_length=2)
    players: list[dict] = Field(max_length=1000)
    data_reference: dict

    def verify(self):
        if self.snapshot.cursor != len(self.events):
            raise ValueError('Snapshot cursor must equal its observed delivery count')
        if any(event.get('match_id') != self.snapshot.match_id for event in self.events):
            raise ValueError('Event belongs to another match')
        # Broadcast clock restarts each period, so compare (period, seconds).
        observed = (self.snapshot.period or 1, self.snapshot.clock_seconds or 0)
        if any(event.get('match_time_seconds', -1) < 0 or position(event) > observed for event in self.events):
            raise ValueError('Event exceeds the observed match clock')
        raw = self.model_dump(mode='json')
        raw['snapshot'].pop('id')
        raw['snapshot'].pop('captured_at')
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != self.snapshot.id:
            raise ValueError('Snapshot content does not match its ID')


class GraphQLQuery(BaseModel):
    query: str = Field(max_length=10000)
    variables: dict = Field(default_factory=dict)
