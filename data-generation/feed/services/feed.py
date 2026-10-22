"""Provider-side control: the catalogue, runs (N at once) and per-match purge (local/contracts.md §5, §7)."""
import asyncio
import logging
import math
import re
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from feed.adapters.hls import LivePlaylist, live_store
from feed.models.stream import MA1_LEAD_SECONDS
from feed.services.run import RunTask, SendPolicy

log = logging.getLogger(__name__)
MATCH_ID = re.compile(r"[a-z0-9-]{1,64}")


class FeedError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def main_first(settings):
    """The demo fixtures, the main game first (it starts first and the viewer opens it)."""
    main = settings.get("main_fixture")
    return [main, *(f for f in settings["fixtures"] if f != main)] if main in settings["fixtures"] \
        else list(settings["fixtures"])


class FeedService:
    def __init__(self, repository, streams, *, sink, clock, live_root, allow_seek=False, policy=SendPolicy(),
                 seeds=False):
        self.repository, self.streams, self.sink, self.clock, self.policy = repository, streams, sink, clock, policy
        self.live, self.allow_seek = live_store(live_root), allow_seek  # LocalLive, or BlobLive on Azure
        self.seeds = seeds  # DEMO_SEEDS=1: seed recording and seeded starts (PLAN.md §10.6); off in production
        self.tasks = {}  # match_id -> (RunTask, asyncio.Task)
        self._lock = asyncio.Lock()
        self.ready = False

    async def start(self):
        await asyncio.to_thread(self.repository.migrate)
        await asyncio.to_thread(self.repository.sync_recordings,
                                [{**s.entry(), "sha256": s.sha256} for s in self.streams.values()])
        for run in await asyncio.to_thread(self.repository.runs):
            if run["status"] != "finished" and run.get("resume_seconds") is None:  # else: still awaiting its seed
                self._launch(run, resume=True)
        self.ready = True

    async def close(self):
        for match_id in list(self.tasks):
            await self._stop(match_id)

    def _playlist(self, stream, match_id):
        return LivePlaylist(stream.media, self.live.dir(match_id)) if stream.media else None

    def _launch(self, run, *, resume=False):
        stream = self.streams.get(run["fixture"])
        if stream is None:
            log.warning("Run %s: fixture %s is no longer available", run["match_id"], run["fixture"])
            return
        playlist = self._playlist(stream, run["match_id"])
        if playlist and resume:
            playlist.resume()
        task = RunTask(run, stream, sink=self.sink, repository=self.repository, clock=self.clock, playlist=playlist,
                       policy=self.policy)
        self.tasks[run["match_id"]] = task, asyncio.create_task(task.run(), name=run["match_id"])

    async def _stop(self, match_id):
        entry = self.tasks.pop(match_id, None)
        if entry:
            entry[1].cancel()
            with suppress(asyncio.CancelledError):
                await entry[1]
            if entry[0].pending:  # e.g. a segment copy: let it land before the purge deletes.
                await asyncio.wait([entry[0].pending])

    def active_runs(self):
        return sum(1 for _, task in self.tasks.values() if not task.done())

    async def recordings(self):
        return await asyncio.to_thread(self.repository.recordings)

    def _kickoff(self, kickoff, start_seconds, duration):
        now = self.clock.now()
        if start_seconds is not None:
            if not self.allow_seek:
                raise FeedError(422, "Seek is disabled (FEED_ALLOW_SEEK).")
            if not 0 <= start_seconds <= duration:
                raise FeedError(422, "start_seconds is outside the recording.")
            return now - timedelta(seconds=start_seconds)
        if kickoff == "next-minute":
            lead = now.timestamp() + MA1_LEAD_SECONDS
            return datetime.fromtimestamp(math.ceil(lead / 60) * 60, timezone.utc)
        try:
            parsed = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
        except ValueError:
            raise FeedError(422, "kickoff must be 'next-minute' or an ISO-8601 UTC time.") from None
        if parsed.tzinfo is None:
            raise FeedError(422, "kickoff needs a UTC offset.")
        if parsed < now:
            raise FeedError(422, "kickoff is in the past.")
        return parsed.astimezone(timezone.utc)

    def _point_seconds(self, settings, fixture, point_id):
        point = next((p for p in settings["start_points"] if p["id"] == point_id), None)
        if point is None:
            raise FeedError(404, f"Unknown start point {point_id}.")
        seconds = self.streams[fixture].video_at(point["period"], point["minute"])
        if seconds is None:
            raise FeedError(409, f"{fixture} never reaches {point['label']}.")
        return seconds

    async def create_run(self, fixture, kickoff="next-minute", start_seconds=None, hold_point=None, resume_point=None):
        """hold_point / resume_point (start point ids, dev only): record a seed. A held run stops sending at the
        point; a resumed one waits for its seed to be restored (`release`), then plays on from that point."""
        stream = self.streams.get(fixture)
        if stream is None:
            raise FeedError(404, "Unknown fixture.")
        if (hold_point or resume_point) and not self.seeds:
            raise FeedError(403, "Seed recording needs DEMO_SEEDS=1.")
        when = self._kickoff(kickoff, start_seconds, stream.duration_seconds)
        async with self._lock:
            settings = await asyncio.to_thread(self.repository.demo_settings)
            if len(await self._active()) >= settings["max_active_runs"]:
                raise FeedError(409, f"{settings['max_active_runs']} runs are already scheduled or live; "
                                     "start one after they finish.")
            hold = self._point_seconds(settings, fixture, hold_point) if hold_point else None
            offset = self._point_seconds(settings, fixture, resume_point) if resume_point else 0.0
            if hold is not None and hold <= offset:
                raise FeedError(422, "The hold point must come after the resume point.")
            run = await self._create(fixture, when, offset, hold=hold, wait=bool(offset), point=resume_point,
                                     held_at=hold_point)
        return self._public(run)

    async def release(self, match_id, after_seconds=0.0):
        """Start a run that waited for its seed: its clock reads the seed's point `after_seconds` from now."""
        async with self._lock:
            run = next((r for r in await asyncio.to_thread(self.repository.runs) if r["match_id"] == match_id), None)
            if run is None:
                raise FeedError(404, "Unknown run.")
            if run.get("resume_seconds") is None:
                return self._public(run)  # Already released: idempotent.
            when = self.clock.now() + timedelta(seconds=after_seconds)
            run = await asyncio.to_thread(self.repository.release, match_id, when - timedelta(seconds=run["resume_seconds"]))
            self._launch(run)
        return self._public(run)

    async def _create(self, fixture, when, offset=0.0, hold=None, wait=False, point=None, held_at=None):
        """Caller holds the lock. offset > 0: the run's clock reads `offset` at `when`; what came before
        is taken as already delivered (a restored seed), so sending resumes at that point without MA1.
        wait: do not start until `release` (after every owner restored the seed)."""
        stream = self.streams[fixture]
        for _ in range(5):
            run_id = uuid.uuid4()
            match_id = f"{fixture}-{run_id.hex[:8]}"
            run = await asyncio.to_thread(self.repository.create_run, str(run_id), match_id, fixture,
                                          when - timedelta(seconds=offset), hold, offset if wait else None,
                                          point if offset else None, held_at)
            if run:
                break
        else:
            raise FeedError(503, "Could not mint a new matchId; retry.")
        if offset:
            position = 1 + sum(1 for item in stream.items if item.at < offset)
            seq = sum(1 for e in stream.events if e["video_seconds"] < offset)
            await asyncio.to_thread(self.repository.progress, run["run_id"], position, seq, "scheduled")
            run = {**run, "position": position, "seq": seq}
        if not wait:
            self._launch(run)
        return run

    async def _active(self):
        return [r for r in await self.runs() if r["status"] != "finished"]

    async def start_demo(self, point_id="kickoff"):
        """One demo at a time: the configured fixtures, staggered, from a configured start point. While any
        run is scheduled or live this starts nothing and returns those runs, so repeated clicks are safe.
        Finished runs are purged first (here; the caller purges the other owners)."""
        async with self._lock:
            active = await self._active()
            if active:
                return {"started": False, "runs": active}
            settings = await asyncio.to_thread(self.repository.demo_settings)
            point = next((p for p in settings["start_points"] if p["id"] == point_id), None)
            if point is None:
                raise FeedError(404, "Unknown start point.")
            missing = [f for f in settings["fixtures"] if f not in self.streams]
            if missing:
                raise FeedError(409, f"Demo fixture(s) not in the catalogue: {', '.join(missing)}.")
            offsets = {f: self.streams[f].video_at(point["period"], point["minute"]) for f in settings["fixtures"]}
            if any(o is None for o in offsets.values()):
                raise FeedError(409, f"A demo fixture never reaches {point['label']}.")
            if any(offsets.values()) and not self.seeds:
                raise FeedError(409, f"Starting from {point['label']} needs DEMO_SEEDS=1.")
            if any(offsets.values()) and not point.get("seed"):
                raise FeedError(409, f"No seed is recorded for {point['label']} yet.")
            finished = [r["match_id"] for r in await asyncio.to_thread(self.repository.runs)]
            if finished:
                await self._purge_ids(finished)
            first = self._kickoff("next-minute", None, 0)
            runs = []
            try:
                for i, f in enumerate(main_first(settings)):  # the main game starts first: furthest along
                    runs.append(await self._create(f, first + timedelta(seconds=i * settings["stagger_seconds"]),
                                                   offsets[f], wait=bool(offsets[f]), point=point_id))
            except Exception:  # never leave a partial demo that every later Start would return
                await self._purge_ids([r["match_id"] for r in runs])
                raise
        return {"started": True, "point": point, "main_fixture": settings["main_fixture"],
                "runs": [self._public(run) for run in runs]}

    async def demo_settings(self):
        return await asyncio.to_thread(self.repository.demo_settings)

    async def save_demo_settings(self, settings, expected_revision):
        fixtures = settings["fixtures"]
        unknown = [f for f in fixtures if f not in self.streams]
        if unknown:
            raise FeedError(422, f"Unknown fixture(s): {', '.join(unknown)}.")
        if len(set(fixtures)) != len(fixtures) or not fixtures:
            raise FeedError(422, "List each demo fixture once.")
        main = settings.get("main_fixture") or fixtures[0]
        if main not in fixtures:
            raise FeedError(422, "The main fixture must be one of the demo fixtures.")
        settings = {**settings, "main_fixture": main, "fixtures": main_first({"fixtures": fixtures, "main_fixture": main})}
        if settings["max_active_runs"] < len(fixtures):
            raise FeedError(422, "max_active_runs must be at least the number of demo fixtures.")
        ids = [p["id"] for p in settings["start_points"]]
        if not ids or len(set(ids)) != len(ids):
            raise FeedError(422, "Give each start point a unique id.")
        saved = await asyncio.to_thread(self.repository.save_demo_settings, settings, expected_revision)
        if saved is None:
            raise FeedError(409, "Someone else saved the demo settings first; reload.")
        return saved

    def _public(self, run):
        entry = self.tasks.get(run["match_id"])
        task = entry[0] if entry else None
        stream = self.streams.get(run["fixture"])
        if task:
            video = task.video_seconds()
        else:
            video = stream.duration_seconds if stream and run["status"] == "finished" else 0.0
        return {"run_id": run["run_id"], "match_id": run["match_id"], "fixture": run["fixture"],
                "kickoff": run["kickoff"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "status": task.status if task else run["status"], "seq": task.seq if task else run["seq"],
                "position": task.position if task else run["position"],
                "awaiting_restore": run.get("resume_seconds") is not None and task is None,
                "hold_seconds": run.get("hold_seconds"), "held_at": run.get("hold_point"),
                "started_from": run.get("start_point"),
                "video_seconds": round(video, 3)}

    async def runs(self):
        return [self._public(run) for run in await asyncio.to_thread(self.repository.runs)]

    async def purge(self, match_id=None, everything=False):
        """Tombstone first, then stop and delete. Idempotent; unknown ids still get a tombstone."""
        if everything == (match_id is not None):
            raise FeedError(422, "Send exactly one of match_id or all: true.")
        if match_id is not None and not MATCH_ID.fullmatch(match_id):
            raise FeedError(422, "Invalid match_id.")
        async with self._lock:
            if everything:
                known = {r["match_id"] for r in await asyncio.to_thread(self.repository.runs)}
                known |= {m for m in await asyncio.to_thread(self.live.match_ids) if MATCH_ID.fullmatch(m)}
                return await self._purge_ids(sorted(known | set(self.tasks)), cutoff=True)
            return await self._purge_ids([match_id])

    async def _purge_ids(self, ids, *, cutoff=False):
        """Caller holds the lock."""
        await asyncio.to_thread(self.repository.tombstone, ids, cutoff=cutoff)
        for mid in ids:
            await self._stop(mid)
        runs = await asyncio.to_thread(self.repository.delete_runs, ids)
        files = 0
        for mid in ids:
            files += await asyncio.to_thread(self.live.remove, mid)
        return {"match_ids": ids, "purged": {"runs": runs, "hls_files": files}}
