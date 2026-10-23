"""One cap on model calls in flight across every match. Waiting calls go by kind (summaries and compressions,
analyses, follow decisions, then authors), then the match served least recently (no starvation), then arrival."""
import asyncio
import itertools
from contextlib import asynccontextmanager

PRIORITY = {"summary": 0, "analysis": 1, "decision": 2, "author": 3}


class ModelGate:
    def __init__(self, limit):
        if limit < 1:
            raise ValueError("model concurrency must be at least 1")
        self.limit, self.running, self.waiting = limit, 0, []
        self.served = {}  # matchId -> stamp of its latest grant
        self.stamps, self.tickets = itertools.count(1), itertools.count()

    @asynccontextmanager
    async def slot(self, match_id, kind):
        if self.running < self.limit and not self.waiting:
            self._grant(match_id)
        else:
            entry = (PRIORITY[kind], next(self.tickets), match_id, asyncio.get_running_loop().create_future())
            self.waiting.append(entry)
            try:
                await entry[3]
            except asyncio.CancelledError:
                if entry in self.waiting:
                    self.waiting.remove(entry)
                elif not entry[3].cancelled():  # granted just before the cancel: hand the slot on
                    self._release()
                raise
        try:
            yield
        finally:
            self._release()

    def forget(self, match_id):
        self.served.pop(match_id, None)

    def _grant(self, match_id):
        self.running += 1
        self.served[match_id] = next(self.stamps)

    def _release(self):
        self.running -= 1
        while self.running < self.limit and self.waiting:
            entry = min(self.waiting, key=lambda w: (w[0], self.served.get(w[2], 0), w[1]))
            self.waiting.remove(entry)
            self._grant(entry[2])
            entry[3].set_result(None)
