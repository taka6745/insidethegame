"""Removable lab snapshot provider; capture only the already delivered prefix."""
import hashlib
import json
from collections import OrderedDict
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

    async def identity(self, *, allow_error=False):
        """Session reads need only identity, never a copy/hash of match history."""
        async with self.lab._lock:
            if self.lab.status == 'error' and not allow_error:
                raise RuleError('snapshot_unavailable', 'Start a new run before asking a match question.', 409)
            return RunIdentity(str(self.lab.run_id), self.lab.source.match_id)

    async def capture(self, cursor=None):
        """The live cursor, or an earlier observed one; never a later one."""
        async with self.lab._lock:
            lab = self.lab
            if lab.status == 'error':
                raise RuleError('snapshot_unavailable', 'Start a new run before asking a match question.', 409)
            if cursor is not None and cursor < lab.position:
                return build_snapshot(lab.source, lab.run_id, cursor)
            return build_snapshot(lab.source, lab.run_id, lab.position, finished=lab.status == 'finished')

    async def track(self, run_id, rule, label):
        return await self.lab.register(rule, label, expected_run_id=run_id)

    @asynccontextmanager
    async def run_guard(self, run_id):
        """Do not permit a replay reset between validation and durable commit."""
        async with self.lab._lock:
            if str(self.lab.run_id) != run_id:
                raise RuleError('run_changed', 'The match run changed before the answer was ready.', 409)
            yield


_BUILT = OrderedDict()  # (recording, run, cursor, finished) -> payload; building is O(history).


def build_snapshot(source, run_id, cursor, *, finished=False):
    """Stable watermark for the demo producer and read-only snapshot provider."""
    key = (source.fingerprint, str(run_id), cursor, finished)
    if key not in _BUILT:
        _BUILT[key] = _build(source, run_id, cursor, finished=finished)
        if len(_BUILT) > 64:
            _BUILT.popitem(last=False)
    payload = _BUILT[key]
    # Capture time is transport metadata, outside the snapshot identity.
    return payload.model_copy(update={'snapshot': payload.snapshot.model_copy(
        update={'captured_at': datetime.now(timezone.utc).isoformat()})})


def _build(source, run_id, cursor, *, finished):
    events = list(source.history(cursor))
    description = source.describe()
    latest = max(events, key=lambda e: (e.period, e.match_time_seconds), default=None)
    snapshot = MatchSnapshot(id='', run_id=str(run_id), match_id=source.match_id,
        recording_hash=source.fingerprint, cursor=cursor,
        clock_seconds=latest.match_time_seconds if latest else None,
        period=latest.period if latest else None, captured_at=datetime.now(timezone.utc).isoformat())
    if finished and source.spec.get('playback'):
        # Full time is at least 90:00 in period 2. Stoppage or extra time already
        # observed is later on the broadcast clock, so never rewind to it.
        full_time = (2, source.spec['playback']['football_duration_seconds'])
        if latest is None or (latest.period, latest.match_time_seconds) < full_time:
            snapshot.period, snapshot.clock_seconds = full_time
    payload = SnapshotInput(snapshot=snapshot, events=events, teams=description['teams'],
        players=description['players'], data_reference=source.data_reference())
    data = payload.identity_dump()
    data['snapshot'].pop('id'); data['snapshot'].pop('captured_at')
    snapshot.id = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return payload
