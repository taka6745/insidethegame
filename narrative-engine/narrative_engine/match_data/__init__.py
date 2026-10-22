"""What the engine reads from the ETL. Every read is bounded so the engine never sees events the
ETL has not announced or committed (SQL may already hold more): MA3 rows by clock and by the committed
canonical seq (`eventSeq <= matchWatermarks.seq`), key events by clock, SPADL actions and catalogue
stats and trends by the canonical seq of the latest MA3 row up to that clock (`event_seq`).

`etl_graphql.GraphQLMatchData` implements `MatchData` against DAB; the in-memory test double
lives in `narrative_engine.devtools.fixture_data` (devtools, not in the service image).
"""
from typing import Optional, Protocol

from narrative_engine.core.models import MatchClock
from narrative_engine.context.render import MatchInfo


class EtlBehind(RuntimeError):
    """The ETL has announced data it has not finished writing yet: retry later."""


class MatchData(Protocol):
    async def match_info(self, match_id) -> MatchInfo: ...

    async def events(self, match_id, start: MatchClock, end: MatchClock, until_sec: int = 59) -> list:
        """Committed MA3 payloads from `start` to `end` inclusive, the last minute up to `until_sec`.
        Raises EtlBehind while that range holds rows past the committed seq."""

    async def actions(self, match_id, after_seq: int, seq: int) -> list:
        """spadlActions rows with after_seq < finalSeq <= seq, by actionId: the actions settled in that span.
        Raises EtlBehind if the SPADL post-processor has not converted through `seq`."""

    async def stats_at(self, match_id, seq: int) -> list:
        """executeStatsAtSeq rows (the SPADL stat catalogue) at canonical `seq`; [] for no seq.
        Raises EtlBehind while they are not available."""

    async def trends_at(self, match_id, seq: int) -> list:
        """Enabled trend rows (indicator x team x window, local/contracts.md §4b) at canonical `seq`, in the
        engine's shape (etl_graphql.trend_rows); [] for no seq. Raises EtlBehind while behind."""

    async def spells_at(self, match_id, seq: int) -> list:
        """Territory and pressure spells up to `seq` (etl_graphql.spell_rows). Raises EtlBehind while behind."""

    async def event_seq(self, match_id, until: MatchClock, until_sec: int = 59) -> Optional[int]:
        """The canonical MatchEvent seq (MA3 `eventSeq`) of the latest MA3 row up to `until`:`until_sec`."""

    async def event_seq_of(self, match_id, event_id) -> Optional[int]:
        """The canonical seq (MA3 `eventSeq`) of the MA3 row with this `id` (a key event's id), or None."""

    async def key_events(self, match_id, until: MatchClock, until_sec: int = 59) -> list:
        """keyEvents rows up to and including `until`:`until_sec`."""

    async def period_end(self, match_id, period_id) -> Optional[MatchClock]:
        """Clock of the period's End event, or None if it has not been written yet."""

    async def period_end_at(self, match_id, period_id) -> Optional[tuple]:
        """(clock, second) of the period's End event, or None."""

    async def raw_event(self, match_id, contestant_id, event_id) -> Optional[dict]:
        """The MA3 payload with this per-contestant Opta eventId (qualifier 55 targets)."""
