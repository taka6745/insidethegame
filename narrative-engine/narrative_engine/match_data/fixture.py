"""What the engine reads from the ETL. Every read is bounded by a match clock so the
engine never sees events the ETL has not announced yet (SQL may already hold more).

`FixtureMatchData` serves a replay file and its notifications in memory, for tests and
offline runs. `etl_graphql.GraphQLMatchData` implements the same methods against DAB.
"""
import json
from typing import Optional, Protocol

from narrative_engine.core.models import MatchClock
from narrative_engine.context.render import MatchInfo


class MatchData(Protocol):
    async def match_info(self, match_id) -> MatchInfo: ...

    async def events(self, match_id, start: MatchClock, end: MatchClock, until_sec: int = 59) -> list:
        """MA3 payloads from `start` to `end` inclusive, the last minute up to `until_sec`."""

    async def stats_as_of(self, match_id, clock: MatchClock, expect_row: bool = False) -> list:
        """matchStatsAsOfs rows (home and away) for the latest minute at or before `clock`.
        `expect_row` means the minute had events, so its row should exist (retry if not)."""

    async def key_events(self, match_id, until: MatchClock, until_sec: int = 59) -> list:
        """keyEvents rows up to and including `until`:`until_sec`."""

    async def period_end(self, match_id, period_id) -> Optional[MatchClock]:
        """Clock of the period's End event, or None if it has not been written yet."""

    async def raw_event(self, match_id, contestant_id, event_id) -> Optional[dict]:
        """The MA3 payload with this per-contestant Opta eventId (qualifier 55 targets)."""


def _position(row):
    return (row["periodId"], row["timeMin"], row["timeSec"])


def _within(row, start, end, until_sec):
    return (start.periodId, start.timeMin, 0) <= _position(row) <= (end.periodId, end.timeMin, until_sec)


class FixtureMatchData:
    """A single synthetic match held in memory; ignores the requested match ID."""

    def __init__(self, match_path, notifications_path=None, stats=None):
        with open(match_path) as f:
            messages = [json.loads(line) for line in f]
        self.info = MatchInfo.from_ma1(next(m for m in messages if m["feed"] == "MA1"))
        self.raw = [m for m in messages if m["feed"] == "MA3"]
        self.keys = []
        if notifications_path:
            with open(notifications_path) as f:
                self.keys = [n for n in map(json.loads, f) if n.get("messageType") == "KeyEventDetected"]
        self.stats = stats or {}  # MatchClock -> rows; empty means "no statistics yet"

    async def match_info(self, match_id):
        return self.info

    async def events(self, match_id, start, end, until_sec=59):
        return [e for e in self.raw if _within(e, start, end, until_sec)]

    async def stats_as_of(self, match_id, clock, expect_row=False):
        known = [c for c in self.stats if c <= clock]
        return self.stats[max(known)] if known else []

    async def key_events(self, match_id, until, until_sec=59):
        start = MatchClock(1, 0)
        return [k for k in self.keys if _within(k, start, until, until_sec)]

    async def period_end(self, match_id, period_id):
        end = next((e for e in self.raw if e["typeId"] == 30 and e["periodId"] == period_id), None)
        return MatchClock(end["periodId"], end["timeMin"]) if end else None

    async def raw_event(self, match_id, contestant_id, event_id):
        return next((e for e in self.raw if e["contestantId"] == contestant_id and e["eventId"] == event_id), None)
