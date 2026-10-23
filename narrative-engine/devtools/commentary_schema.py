"""Executable schema of the authored commentary fixtures (docs/components/fixtures.md): schema v2, N broadcast
minutes x 12 bucket versions, tiers and key moments, plus the broadcast-clock helpers the binder uses.
Developer tooling only: the engine never reads these fixtures.

Broadcast clock: periods restart at nominal times and run into stoppage. Clock seconds alone are
ambiguous (45:30 exists in both halves), so every comparison uses (period, seconds) or delivery order.
"""
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PERIOD_START_SECONDS = {1: 0, 2: 2700, 3: 5400, 4: 6300, 5: 7200}
PERIOD_END_MINUTE = {1: 45, 2: 90, 3: 105, 4: 120}


def position(event):
    return (event.get('period') or 1, event['match_time_seconds'])


def minute_label(period, minute):
    """Broadcast minute (1-based, timeMin + 1): period 1 minute 47 is 45+2'."""
    end = PERIOD_END_MINUTE.get(period)
    return f"{end}+{minute - end}'" if end is not None and minute > end else f"{minute}'"


def minute_id(period, minute):
    return f'p{period}-m{minute}'


BUCKETS = tuple(f'{team}:{style}' for team in ('home', 'away', 'neutral')
                for style in ('simple', 'casual', 'experienced', 'analytical'))
TIERS = ('five-minute', 'ten-minute', 'twenty-minute', 'half')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Release(Strict):
    """First observed position at which the unit may be shown."""
    cursor: int = Field(ge=1)
    period: int = Field(ge=1, le=5)
    clock_seconds: int = Field(ge=0)
    video_seconds: float = Field(ge=0)
    prefix_digest: str = Field(min_length=64, max_length=64)


class BucketText(Strict):
    bucket_id: Literal[BUCKETS]
    text: str = Field(min_length=1, max_length=3000)
    stat_ids: list[str] = Field(max_length=30)


class Minute(Strict):
    id: str
    period: int = Field(ge=1, le=5)
    minute: int = Field(ge=1)
    label: str
    start_seconds: int = Field(ge=0)
    end_seconds: int
    release: Release
    evidence: list[dict] = Field(min_length=1)
    recap: str = Field(min_length=1, max_length=3000)
    narratives: list[BucketText] = Field(max_length=len(BUCKETS))

    @model_validator(mode='after')
    def consistent(self):
        if (self.id, self.label) != (minute_id(self.period, self.minute), minute_label(self.period, self.minute)):
            raise ValueError(f'Minute {self.id} id/label do not match its period and minute')
        if (self.start_seconds, self.end_seconds) != ((self.minute - 1) * 60, self.minute * 60):
            raise ValueError(f'Minute {self.id} interval must be its broadcast minute')
        if len({row.bucket_id for row in self.narratives}) != len(self.narratives):
            raise ValueError(f'Minute {self.id} repeats a bucket')
        return self


class Tier(Strict):
    id: str
    tier: Literal[TIERS]
    period: int = Field(ge=1, le=5)
    start_seconds: int = Field(ge=0)
    end_seconds: int
    child_ids: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=5000)
    release: Release


class KeyMoment(Strict):
    id: str
    rank: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=3000)
    event_ids: list[str] = Field(min_length=1)
    period: int = Field(ge=1, le=5)
    minute: int = Field(ge=1)
    label: str
    start_video_seconds: float = Field(ge=0)
    end_video_seconds: float = Field(ge=0)
    release: Release
    evidence: list[dict] = Field(min_length=1)

    @model_validator(mode='after')
    def consistent(self):
        if self.end_video_seconds < self.start_video_seconds:
            raise ValueError(f'Key moment {self.id} ends before it starts')
        if [row['event_id'] for row in self.evidence] != self.event_ids:
            raise ValueError(f'Key moment {self.id} evidence must be its events')
        return self


class NarrativeFixture(Strict):
    schema_version: Literal[2]
    recording_hash: str = Field(min_length=64, max_length=64)
    synthetic: Literal[True]
    provenance: dict
    minutes: list[Minute] = Field(min_length=1)
    tiers: list[Tier] = Field(default_factory=list)
    key_moments: list[KeyMoment] = Field(default_factory=list)

    @model_validator(mode='after')
    def hierarchy(self):
        ids = [row.id for row in (*self.minutes, *self.tiers, *self.key_moments)]
        if len(ids) != len(set(ids)):
            raise ValueError('Fixture IDs must be unique')
        if len({row.rank for row in self.key_moments}) != len(self.key_moments):
            raise ValueError('Key moment ranks must be unique')
        blocks = {row.id: row for row in (*self.minutes, *self.tiers)}
        for tier in self.tiers:
            children = [blocks.get(child) for child in tier.child_ids]
            if None in children or any(child.period != tier.period for child in children):
                raise ValueError(f'Tier {tier.id} has a missing or other-period child')
            bounds = [tier.start_seconds] + [edge for child in children for edge in (child.start_seconds, child.end_seconds)] + [tier.end_seconds]
            if bounds[0::2] != bounds[1::2]:
                raise ValueError(f'Tier {tier.id} children must cover its interval contiguously')
            if any(child.release.cursor > tier.release.cursor for child in children):
                raise ValueError(f'Tier {tier.id} is released before a child')
        return self


def prefix_digests(events, cursors):
    """Digest of each requested delivery prefix in one pass (None marks a deleted event)."""
    wanted, digest, result = set(cursors), hashlib.sha256(), {}
    for index, event in enumerate(events, 1):
        digest.update(json.dumps(event, sort_keys=True, separators=(',', ':')).encode() + b'\n')
        if index in wanted:
            result[index] = digest.hexdigest()
    return result
