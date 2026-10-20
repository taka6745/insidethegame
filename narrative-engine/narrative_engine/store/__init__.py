"""Narrative Store: match checkpoints, context blocks and narratives, all scoped by matchId.

The memory store backs tests and local runs; Cosmos DB (phase 6) implements the same methods.
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

    async def add_narrative(self, narrative: Narrative) -> None: ...

    async def narratives(self, match_id, user_type=None) -> list:
        """Narratives in creation order (per user type, `seq` order)."""

    async def narratives_after(self, match_id, user_type, after_seq, limit) -> list:
        """Up to `limit` of one bucket's narratives with seq > after_seq, in seq order."""

    async def narrative_for_step(self, match_id, user_type, step_id) -> Optional[Narrative]: ...

    async def live_match_ids(self) -> list:
        """Matches whose checkpoint is still live (the only cross-match read; used on startup)."""
