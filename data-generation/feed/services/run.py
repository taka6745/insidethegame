"""One run on the wall clock: MA1 before kickoff, then the stream at video pace, HLS as it plays.

Position counts items sent: 0 = nothing, 1 = MA1, then FixtureStream.items in order. Nothing is
sent before its time, so data past the run's clock never leaves the feed.
"""
import asyncio
import logging
import os
from bisect import bisect_right
from dataclasses import dataclass
from datetime import timedelta

from feed.models.stream import MA1_LEAD_SECONDS
from feed.services.render import RunRenderer

log = logging.getLogger(__name__)
MAX_WAIT = 1.0


@dataclass(frozen=True)
class SendPolicy:
    """Event Hubs send tunables (FEED_SEND_* settings). Ingress is about 1,000 events/s per throughput unit
    (the emulator throttles larger requests), so a backlog after a stall goes out in capped steps instead of
    one batch that would be refused forever. A refused send backs off (retry_first doubling up to retry_max);
    throttling ("server-busy") waits at least the throttle_wait the hub asks for. Unsent items stay due and
    go out in order; video keeps publishing."""
    max_items: int = 200
    retry_first: float = 2.0
    retry_max: float = 60.0
    throttle_wait: float = 10.0

    @classmethod
    def from_env(cls, env=os.environ):
        return cls(int(env.get("FEED_SEND_MAX_ITEMS", cls.max_items)),
                   float(env.get("FEED_SEND_RETRY_FIRST_SECONDS", cls.retry_first)),
                   float(env.get("FEED_SEND_RETRY_MAX_SECONDS", cls.retry_max)),
                   float(env.get("FEED_SEND_THROTTLE_WAIT_SECONDS", cls.throttle_wait)))


class RunTask:
    def __init__(self, run, stream, *, sink, repository, clock, playlist=None, policy=SendPolicy()):
        self.run_id, self.match_id, self.kickoff = run["run_id"], run["match_id"], run["kickoff"]
        self.position, self.seq, self.status = run["position"], run["seq"], run["status"]
        self.hold = run.get("hold_seconds")  # A recording run sends nothing at or past this video second.
        self.stream, self.sink, self.repository, self.clock, self.playlist = stream, sink, repository, clock, playlist
        self.policy = policy
        self.renderer = RunRenderer(stream, run_id=self.run_id, match_id=self.match_id, kickoff=self.kickoff,
                                    video=playlist is not None)
        self.times = [-MA1_LEAD_SECONDS] + [item.at for item in stream.items]
        self._saved = self.position, self.status
        self.pending = None  # In-flight thread work; a stop waits for it (FeedService._stop).
        self.failures, self.retry_at = 0, None  # Consecutive refused sends; no send before retry_at.

    def video_seconds(self):
        elapsed = (self.clock.now() - self.kickoff).total_seconds()
        if self.hold is not None:
            elapsed = min(elapsed, self.hold)
        return min(max(0.0, elapsed), self.stream.duration_seconds)

    def _render(self, position):
        if position == 0:
            return self.renderer.ma1(self.clock.now())
        return self.renderer.item(self.stream.items[position - 1])

    async def _blocking(self, fn, *args):
        """Cancelling the task cannot stop a thread, so keep it for _stop to wait on."""
        self.pending = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        return await asyncio.shield(self.pending)

    async def tick(self):
        """Send everything due, publish played segments, save progress. True when finished."""
        clock = (self.clock.now() - self.kickoff).total_seconds()
        if self.hold is not None:
            clock = min(clock, self.hold - 1e-6)
        due = bisect_right(self.times, clock)
        try:
            if due > self.position and (self.retry_at is None or self.clock.now() >= self.retry_at):
                await self._send(due)
        finally:  # Video keeps playing while the data link retries.
            if self.playlist:
                await self._blocking(self.playlist.publish, clock)
        done = self.position == len(self.times) and (self.playlist is None or self.playlist.complete)
        status = "finished" if done else "live" if clock >= 0 else "scheduled"
        if (self.position, status) != self._saved:
            await self._blocking(self.repository.progress, self.run_id, self.position, self.seq, status)
            self._saved = self.position, status
        self.status = status
        return done

    async def _send(self, due):
        """Due items in capped sends; after a refusal, what went out counts and the rest waits for retry_at."""
        policy = self.policy
        while due > self.position:
            bodies = [self._render(p) for p in range(self.position, min(due, self.position + policy.max_items))]
            try:
                await self.sink.send(self.match_id, bodies)
            except Exception as exc:
                self._advance(bodies[:getattr(exc, "sent", 0)])
                self.failures += 1
                delay = min(policy.retry_max, policy.retry_first * 2 ** (self.failures - 1))
                throttled = getattr(exc, "throttled", False)
                delay = max(delay, policy.throttle_wait) if throttled else delay
                self.retry_at = self.clock.now() + timedelta(seconds=delay)
                log.warning("Run %s: send refused (%s); retrying in %.0f s", self.match_id, exc, delay,
                            exc_info=not throttled)
                return
            self._advance(bodies)
        self.failures, self.retry_at = 0, None

    def _advance(self, bodies):
        self.position += len(bodies)
        self.seq = max([b["seq"] for b in bodies if b.get("type") == "MatchEvent"], default=self.seq)

    def wait(self):
        """Seconds until something new is due (capped)."""
        clock = (self.clock.now() - self.kickoff).total_seconds()
        if self.hold is not None and clock >= self.hold:
            return MAX_WAIT
        upcoming = [t for t in (self._next_send(),
                                self.playlist.next_end() if self.playlist else None) if t is not None]
        return min([MAX_WAIT, *(max(0.0, t - clock) for t in upcoming)])

    def _next_send(self):
        """Run time of the next send: the next item, not before a refused send's retry_at."""
        if self.position >= len(self.times):
            return None
        retry = (self.retry_at - self.kickoff).total_seconds() if self.retry_at else None
        return max(self.times[self.position], retry) if retry is not None else self.times[self.position]

    async def run(self):
        while True:
            try:
                if await self.tick():
                    log.info("Run %s finished", self.match_id)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Run %s delayed; retrying", self.match_id)  # Unsent items stay due.
                await self.clock.sleep(2)
                continue
            await self.clock.sleep(self.wait())
