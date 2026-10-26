"""Application service: Event Hubs batches in, SQL rows and outbox notifications out.

Per match it keeps the gate (MA1 stored, no tombstone, MA1 not before the purge-all cut-off), the
latest canonical seq and the watermark: the highest seq whose MA3 rows and earlier POS samples are
committed. Event s's MA3 rows follow it, so s is complete once anything else arrives for the match
(its next event or a POS sample), or after a short quiet spell. Idle flushes are per match.
"""
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from local_stream.processor import Output, StreamProcessor
from reference import pipeline

log = logging.getLogger(__name__)


@dataclass
class MatchState:
    periods: int | None = None  # MA1 capabilities.periods: its final period_end finishes the match
    status: str = "scheduled"
    seq: int = 0  # latest canonical seq received
    watermark: int = 0  # latest complete canonical seq
    sample: int = 0  # latest POS sampleId
    final: int | None = None  # seq of the final period_end


class StreamWorker:
    def __init__(self, repository, window_seconds=60, idle_seconds=75, watermark_idle_seconds=3, clock=time.monotonic):
        self.repository, self.window, self.clock = repository, window_seconds, clock
        self.idle_seconds, self.watermark_idle_seconds = idle_seconds, watermark_idle_seconds
        # Re-entrant: purge and failed commits reload under it. A reconnect's load must not share the
        # SQL connection with a batch still finishing on the old receiver thread (pymssql aborts).
        self.lock = threading.RLock()
        self.checkpoints, self.processor = {}, None
        self.matches, self.seen, self.purged, self.cutoff = {}, {}, set(), None
        self.gapped = set()  # matches whose canonical seq has a hole (logged once)

    def load(self):
        """(Re)build match, tombstone and window state from SQL; returns Event Hubs checkpoints by partition."""
        with self.lock:
            try:
                state = self.repository.load()
            except Exception:
                self.repository.rollback()  # Reconnects a dead connection; the consumer retries.
                raise
            self.checkpoints = state["checkpoints"]
            self.processor = StreamProcessor(self.window, state["closed"])
            for message in state["pending"]:
                self.processor.restore(message)
            self.matches = {m: MatchState(**s) for m, s in state["matches"].items()}
            now = self.clock()
            self.seen = {m: now for m in [*self.matches, *self.processor.open]}
            self.purged, self.cutoff = set(state["purged"]), state["cutoff"]
            return self.checkpoints

    def reset_checkpoint(self, partition_id):
        """The hub was reset: a stored position would later skip the new incarnation's events."""
        with self.lock:
            try:
                self.repository.reset_checkpoint(partition_id)
            except Exception:
                self.repository.rollback()
                raise
            self.checkpoints.pop(partition_id, None)

    def handle(self, partition_id, events):
        """events: [(sequenceNumber, body)]; an empty list means the partition was idle."""
        with self.lock:
            out, before, batch_ids = Output(), dict(self.processor.closed), set()
            progress_before = {m: (s.watermark, s.status) for m, s in self.matches.items()}
            for _, body in events:
                message = parse(body)
                if message is None:
                    continue
                known = message["matchId"] in self.matches
                try:
                    if not self._accept(message, batch_ids):
                        continue
                    out.extend(self.processor.process(message))
                except (AttributeError, KeyError, TypeError, ValueError) as exc:
                    # Stream Analytics' "drop" error policy: a malformed message (envelope or body) is logged
                    # and skipped rather than block its partition. Row building fails before any window changes.
                    log.warning("Dropped a malformed %s message for %s (%s: %s)", pipeline.kind(message),
                                message["matchId"], type(exc).__name__, exc)
                    if pipeline.kind(message) == "MA1" and not known:  # undo only the state this message began
                        self.matches.pop(message["matchId"], None)
                    continue
                self._advance(message)
            out.extend(self._idle())
            progress = {m: (s.watermark, s.status) for m, s in self.matches.items()
                        if progress_before.get(m, (0, "scheduled")) != (s.watermark, s.status)}
            if events or out.rows or out.notifications or progress:
                self._commit(out, before, progress, (partition_id, events[-1][0]) if events else None)

    def purge(self, match_id=None, repository=None):
        """Tombstone, then delete one match, or every match plus a cut-off when match_id is None.
        Later deliveries for tombstoned matches are dropped, also after a restart."""
        with self.lock:
            repository = repository or self.repository
            cutoff = None if match_id else datetime.now(timezone.utc)
            try:
                result = repository.purge(match_id, cutoff)
            except Exception:
                repository.rollback()
                raise
            self.load()
            return result

    def _accept(self, message, batch_ids):
        match_id, feed = message["matchId"], pipeline.kind(message)
        if match_id in self.purged:
            return False
        state = self.matches.get(match_id)
        if feed == "MA1":
            if state is not None:
                return False  # Redelivery.
            if self.cutoff and pipeline.parse_time(message["timeStamp"]) < self.cutoff:
                return False  # Sent before a purge of every match.
            self.matches[match_id] = MatchState(periods=(message.get("capabilities") or {}).get("periods"))
            return True
        if state is None:
            return False  # No stored MA1: in-flight messages never create or revive a match.
        if feed == "MA3":
            key = (match_id, message["id"])
            if key in batch_ids or self.repository.seen(*key):
                return False  # Redelivery: already counted.
            batch_ids.add(key)
        elif feed == "MatchEvent":
            if message["seq"] <= state.seq:
                return False
            if message["seq"] != state.seq + 1:
                # Lost events (e.g. the Event Hubs emulator restarted): the watermark stays before
                # the gap rather than count a partial history (local/README.md Contracts §1).
                if match_id not in self.gapped:
                    log.warning("MatchEvent %s:%s after seq %s: events were lost; the match stays at seq %s",
                                match_id, message["seq"], state.seq, state.seq)
                    self.gapped.add(match_id)
                return False
            event = message.get("event") or {}
            if event.get("match_id") != match_id or event.get("sequence") != message["seq"]:
                log.warning("Dropped a MatchEvent whose event does not match its envelope (%s:%s)", match_id, message["seq"])
                return False
        elif feed == "POS" and message["sampleId"] <= state.sample:
            return False
        return True

    def _advance(self, message):
        match_id, feed = message["matchId"], pipeline.kind(message)
        state = self.matches[match_id]
        self.seen[match_id] = self.clock()
        if feed == "MatchEvent":
            self._complete(state, state.seq)  # The previous event's MA3 rows have all arrived.
            event = message["event"]
            state.seq = message["seq"]
            state.status = "live" if state.status == "scheduled" else state.status
            if (state.final is None and state.periods and event["event_type"] == "period_end"
                    and event.get("period") == state.periods and not event.get("deleted")):
                state.final = state.seq
        elif feed == "POS":
            state.sample = message["sampleId"]
            self._complete(state, state.seq)

    @staticmethod
    def _complete(state, seq):
        if seq > state.watermark:
            state.watermark = seq
            if state.final and seq >= state.final:
                state.status = "finished"

    def _idle(self):
        """Per match: complete the latest event after a short quiet spell; close windows after a long one."""
        now, out = self.clock(), Output()
        for match_id, seen in self.seen.items():
            state = self.matches.get(match_id)
            if state and state.seq > state.watermark and now - seen >= self.watermark_idle_seconds:
                self._complete(state, state.seq)
            if self.processor.open.get(match_id) and now - seen >= self.idle_seconds:
                out.extend(self.processor.flush(match_id))
        return out

    def _commit(self, out, before, progress, checkpoint=None):
        changed = {m: end for m, end in self.processor.closed.items() if before.get(m) != end}
        try:
            self.repository.write(out, changed, checkpoint, progress)
            for n in out.notifications:
                log.info("%s %s %s:%s", n["messageType"], n["matchId"], n["periodId"], n.get("timeMin"))
        except Exception:
            # Discard in-memory progress: the consumer restarts from the committed checkpoint.
            self.repository.rollback()
            self.load()
            raise


def parse(body):
    """MA1/MA3/POS and MatchEvent v2 messages only; probes and other kinds on the same hub are ignored."""
    try:
        message = json.loads(body)
    except ValueError:
        log.warning("Ignored a non-JSON Event Hubs message")
        return None
    if not pipeline.kind(message):
        return None
    if not isinstance(message["matchId"], str):  # It keys every per-match set and dict below.
        log.warning("Dropped a message whose matchId is not a string")
        return None
    return message
