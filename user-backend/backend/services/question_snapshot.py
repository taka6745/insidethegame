"""Removable lab snapshot provider; capture only the already delivered prefix."""
import hashlib
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from dataclasses import dataclass
from backend.models.questions import MatchSnapshot, SnapshotInput
from backend.domain import RuleError


@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    match_id: str


class LabSnapshotProvider:
    def __init__(self, lab):
        self.lab = lab

    async def identity(self):
        """Session reads need only identity, never a copy/hash of match history."""
        async with self.lab._lock:
            if self.lab.status == 'error':
                raise RuleError('snapshot_unavailable', 'Start a new run before asking a match question.', 409)
            return RunIdentity(str(self.lab.run_id), self.lab.source.match_id)

    async def capture(self):
        async with self.lab._lock:
            lab = self.lab
            if lab.status == 'error':
                raise RuleError('snapshot_unavailable', 'Start a new run before asking a match question.', 409)
            events = list(lab.source.history(lab.position))
            description = lab.source.describe()
            latest = max(events, key=lambda e: (e.period, e.match_time_seconds), default=None)
            snapshot = MatchSnapshot(id='', run_id=str(lab.run_id), match_id=lab.source.match_id,
                recording_hash=lab.source.fingerprint, cursor=lab.position,
                clock_seconds=latest.match_time_seconds if latest else None,
                period=latest.period if latest else None, captured_at=datetime.now(timezone.utc).isoformat())
            if lab.status == 'finished' and lab.source.spec.get('playback'):
                snapshot.clock_seconds = lab.source.spec['playback']['football_duration_seconds']
                snapshot.period = 2
            payload = SnapshotInput(snapshot=snapshot, events=events, teams=description['teams'],
                players=description['players'], data_reference=lab.source.data_reference())
            data = payload.model_dump(mode='json')
            data['snapshot'].pop('id'); data['snapshot'].pop('captured_at')
            snapshot.id = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            return payload

    async def track(self, run_id, rule, label):
        return await self.lab.register(rule, label, expected_run_id=run_id)

    @asynccontextmanager
    async def run_guard(self, run_id):
        """Do not permit a replay reset between validation and durable commit."""
        async with self.lab._lock:
            if str(self.lab.run_id) != run_id:
                raise RuleError('run_changed', 'The match run changed before the answer was ready.', 409)
            yield
