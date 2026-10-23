"""Test double for `match_data.MatchData`: a replay file, its notifications and its SPADL actions
served from memory, for tests and offline runs. Never used by the service.

A replay without canonical seqs (the seeder's itg-syn-0001) uses each MA3 row's `seq` as its
`eventSeq`; devtools/spadl_fixture.py converts such a replay the same way."""
import json
from bisect import bisect_right
from itertools import accumulate

from narrative_engine.core.models import MatchClock
from narrative_engine.context.render import MatchInfo


def _position(row):
    return (row["periodId"], row["timeMin"], row["timeSec"])


def _within(row, start, end, until_sec):
    return (start.periodId, start.timeMin, 0) <= _position(row) <= (end.periodId, end.timeMin, until_sec)


class FixtureMatchData:
    """A single synthetic match held in memory; ignores the requested match ID."""

    def __init__(self, match_path, notifications_path=None, stats=None, actions_path=None, keys=None, trends=None,
                 spells=None):
        with open(match_path) as f:
            messages = [json.loads(line) for line in f]
        self.info = MatchInfo.from_ma1(next(m for m in messages if m["feed"] == "MA1"))
        self.raw = [{**m, "eventSeq": m.get("eventSeq", m["seq"])} for m in messages if m["feed"] == "MA3"]
        self.keys = keys or []
        if notifications_path:
            with open(notifications_path) as f:
                self.keys = [n for n in map(json.loads, f) if n.get("messageType") == "KeyEventDetected"]
        self.actions_rows = []
        if actions_path:
            with open(actions_path) as f:
                self.actions_rows = json.load(f)["actions"]
        self._finals = [a["finalSeq"] for a in self.actions_rows]  # non-decreasing in actionId order
        ordered = sorted((_position(e), e["eventSeq"]) for e in self.raw)
        self._positions = [p for p, _ in ordered]
        self._latest = list(accumulate((seq for _, seq in ordered), max))  # latest seq up to each position
        self.stats = stats or {}  # seq -> executeStatsAtSeq rows; empty means "no statistics yet"
        self.trends, self.spells = trends, spells  # seq -> rows (e.g. etl/reference/trends.py); None: no trends

    async def match_info(self, match_id):
        return self.info

    async def events(self, match_id, start, end, until_sec=59):
        return [e for e in self.raw if _within(e, start, end, until_sec)]

    async def actions(self, match_id, after_seq, seq):
        lo, hi = bisect_right(self._finals, after_seq), bisect_right(self._finals, seq or 0)
        return self.actions_rows[lo:hi]

    async def stats_at(self, match_id, seq):
        known = [s for s in self.stats if s <= (seq or 0)]
        return self.stats[max(known)] if known else []

    async def trends_at(self, match_id, seq):
        return self.trends(seq) if self.trends and seq else []

    async def spells_at(self, match_id, seq):
        return self.spells(seq) if self.spells and seq else []

    async def event_seq(self, match_id, until, until_sec=59):
        i = bisect_right(self._positions, (until.periodId, until.timeMin, until_sec))
        return self._latest[i - 1] if i else None

    async def event_seq_of(self, match_id, event_id):
        return next((e["eventSeq"] for e in self.raw if e["id"] == event_id), None)

    async def key_events(self, match_id, until, until_sec=59):
        start = MatchClock(1, 0)
        return [k for k in self.keys if _within(k, start, until, until_sec)]

    async def period_end(self, match_id, period_id):
        end = await self.period_end_at(match_id, period_id)
        return end and end[0]

    async def period_end_at(self, match_id, period_id):
        end = next((e for e in self.raw if e["typeId"] == 30 and e["periodId"] == period_id), None)
        return (MatchClock(end["periodId"], end["timeMin"]), end["timeSec"]) if end else None

    async def raw_event(self, match_id, contestant_id, event_id):
        return next((e for e in self.raw if e["contestantId"] == contestant_id and e["eventId"] == event_id), None)
