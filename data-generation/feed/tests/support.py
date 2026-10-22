"""Test doubles: a virtual clock, a recording sink and an in-memory repository."""
import asyncio
import functools
from datetime import timedelta
from pathlib import Path

from feed.adapters.recordings import load

RECORDINGS = Path(__file__).resolve().parents[2] / "recordings"


@functools.cache
def riverton():
    return load(RECORDINGS / "riverton-forgeham-grf.json")


class FakeClock:
    """Sleepers wake only when a test advances time; advance() waits until every task parks again."""

    def __init__(self, start):
        self.t, self.targets = start, []
        self._changed = asyncio.Condition()

    def now(self):
        return self.t

    async def sleep(self, seconds):
        target = self.t + timedelta(seconds=seconds)
        async with self._changed:
            self.targets.append(target)
            try:
                await self._changed.wait_for(lambda: self.t >= target)
            finally:
                self.targets.remove(target)

    async def settle(self, service):
        for _ in range(2000):
            active = sum(1 for _, task in service.tasks.values() if not task.done())
            if len(self.targets) >= active and all(t > self.t for t in self.targets):
                return
            await asyncio.sleep(0.002)
        raise AssertionError("tasks did not settle")

    async def advance(self, seconds, service):
        self.t += timedelta(seconds=seconds)
        async with self._changed:
            self._changed.notify_all()
        await self.settle(service)


class FakeSink:
    def __init__(self, clock):
        self.clock, self.sent = clock, []  # (partition key, body, clock at send)

    async def send(self, partition_key, bodies):
        self.sent += [(partition_key, body, self.clock.now()) for body in bodies]

    def bodies(self, match_id=None, kind=None):
        return [b for key, b, _ in self.sent if (match_id is None or key == match_id) and
                (kind is None or b.get("feed", b.get("type")) == kind)]


class MemoryRepository:
    def __init__(self, clock):
        self.clock, self.catalogue, self.rows, self.tombstones, self.cutoff = clock, [], {}, set(), None
        self.demo = {"fixtures": ["riverton-forgeham"], "main_fixture": "riverton-forgeham", "stagger_seconds": 120, "max_active_runs": 3,
                     "start_points": [{"id": "kickoff", "label": "Kick-off", "period": 1, "minute": 0, "seed": None},
                                      {"id": "20", "label": "20′", "period": 1, "minute": 20, "seed": None}],
                     "skip_targets": [{"id": "10", "label": "+10′", "minutes": 10},
                                      {"id": "to-20", "label": "20′", "point": "20"}], "revision": 1}

    def migrate(self):
        pass

    def sync_recordings(self, entries):
        self.catalogue = [{k: v for k, v in e.items() if k != "sha256"} for e in entries]

    def recordings(self):
        return self.catalogue

    def create_run(self, run_id, match_id, fixture, kickoff, hold_seconds=None, resume_seconds=None, start_point=None,
                   hold_point=None):
        if match_id in self.tombstones:
            return None
        self.rows[run_id] = {"run_id": run_id, "match_id": match_id, "fixture": fixture, "kickoff": kickoff,
                             "created_at": self.clock.now(), "status": "scheduled", "position": 0, "seq": 0,
                             "hold_seconds": hold_seconds, "resume_seconds": resume_seconds,
                             "start_point": start_point, "hold_point": hold_point}
        return dict(self.rows[run_id])

    def release(self, match_id, kickoff):
        row = next((r for r in self.rows.values() if r["match_id"] == match_id and r["resume_seconds"] is not None), None)
        if row is None:
            return None
        row.update(kickoff=kickoff, resume_seconds=None)
        return dict(row)

    def runs(self):
        return [dict(r) for r in self.rows.values() if r["match_id"] not in self.tombstones and
                (self.cutoff is None or r["created_at"] > self.cutoff)]

    def progress(self, run_id, position, seq, status):
        if run_id in self.rows:
            self.rows[run_id].update(position=position, seq=seq, status=status)

    def tombstone(self, match_ids, *, cutoff=False):
        self.tombstones |= set(match_ids)
        self.cutoff = self.clock.now() if cutoff else self.cutoff

    def demo_settings(self):
        return dict(self.demo)

    def save_demo_settings(self, settings, expected_revision):
        if expected_revision != self.demo["revision"]:
            return None
        skips = settings.get("skip_targets")
        self.demo = {**settings, "skip_targets": self.demo["skip_targets"] if skips is None else skips,
                     "revision": expected_revision + 1}
        return dict(self.demo)

    def shift_kickoff(self, match_id, seconds):
        row = next((r for r in self.rows.values() if r["match_id"] == match_id and r["status"] != "finished"), None)
        if row is None:
            return None
        row["kickoff"] -= timedelta(seconds=seconds)
        return dict(row)

    def delete_runs(self, match_ids):
        doomed = [k for k, r in self.rows.items() if r["match_id"] in match_ids]
        for k in doomed:
            del self.rows[k]
        return len(doomed)


def media(directory, segments=10, duration=2.0):
    """A packaged HLS directory with tiny fake segments."""
    directory.mkdir(parents=True)
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:2", "#EXT-X-PLAYLIST-TYPE:VOD"]
    for i in range(segments):
        (directory / f"{i:05d}.ts").write_bytes(b"segment %d" % i)
        lines += [f"#EXTINF:{duration:.6f},", f"{i:05d}.ts"]
    (directory / "match.m3u8").write_text("\n".join(lines + ["#EXT-X-ENDLIST"]) + "\n")
    return directory
