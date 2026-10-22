"""Narrative Store: match checkpoints, context blocks, narratives, match analyses (immutable snapshots),
storylines (their current projection), story-follow decisions (immutable) and follow narratives, all scoped
by matchId, plus the purge tombstones that keep a purged match from coming back.

The memory store backs tests and local runs; Cosmos DB (the service) implements the same methods.
"""
from typing import Optional, Protocol

from narrative_engine.core.models import ContextBlock, Narrative


class Store(Protocol):
    async def get_checkpoint(self, match_id) -> Optional[dict]: ...

    async def save_checkpoint(self, match_id, checkpoint: dict) -> None: ...

    async def put_block(self, block: ContextBlock) -> None:
        """Upsert by id, so a re-run summary overwrites rather than duplicates."""

    async def supersede(self, block: ContextBlock, input_ids) -> None:
        """Write `block`, then mark the inputs superseded by it (one batch in Cosmos)."""

    async def active_blocks(self, match_id) -> list:
        """Non-superseded blocks in match order."""

    async def all_blocks(self, match_id) -> list:
        """Every block, superseded ones included."""

    async def put_analysis(self, analysis: dict) -> None:
        """Write a match analysis once; it never changes (a re-run reuses it)."""

    async def get_analysis(self, match_id, analysis_id) -> Optional[dict]: ...

    async def analyses(self, match_id) -> list:
        """Every analysis of the match, in horizon order."""

    async def put_storylines(self, match_id, storylines: list) -> None:
        """Upsert the storylines' current state (the projection of the latest analysis)."""

    async def storylines(self, match_id) -> list:
        """The match's storylines, in the order they opened."""

    async def delete_match(self, match_id) -> dict:
        """Remove one match's documents in every container; returns rows deleted per container."""

    async def match_ids(self) -> list:
        """Every match with a checkpoint (purge all)."""

    async def add_tombstones(self, match_ids, cutoff=None) -> None:
        """Mark matches purged for good; `cutoff` (ISO time) also drops any match whose MA1 is older."""

    async def tombstones(self) -> tuple:
        """(set of purged matchIds, latest purge-all cut-off or None); read on startup."""

    async def add_narrative(self, narrative: Narrative) -> None: ...

    async def narratives(self, match_id, user_type=None) -> list:
        """Narratives in creation order (per user type, `seq` order)."""

    async def narratives_after(self, match_id, user_type, after_seq, limit) -> list:
        """Up to `limit` of one bucket's narratives with seq > after_seq, in seq order."""

    async def narrative_for_step(self, match_id, user_type, step_id) -> Optional[Narrative]: ...

    async def put_decision(self, decision: dict) -> None:
        """Write a follow decision once; it never changes (a retry or restart reuses it)."""

    async def get_decision(self, match_id, decision_id) -> Optional[dict]: ...

    async def decisions(self, match_id) -> list:
        """Every follow decision of the match, in horizon order."""

    async def add_subscription_narrative(self, narrative: Narrative) -> None: ...

    async def subscription_narratives(self, match_id, topic_id=None, user_type=None) -> list:
        """Follow narratives in creation order."""

    async def subscription_narratives_after(self, match_id, topic_id, user_type, after_seq, limit) -> list:
        """Up to `limit` of one (topic, bucket)'s narratives with seq > after_seq, in seq order."""

    async def subscription_narrative_for_step(self, match_id, topic_id, user_type, step_id) -> Optional[Narrative]: ...

    async def live_match_ids(self) -> list:
        """Matches still live or with queued steps, e.g. a pending full-time step (used on startup)."""
