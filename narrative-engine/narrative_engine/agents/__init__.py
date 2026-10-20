"""The three agents. Each takes the prompt variables named in prompts/*.txt, as strings.

summarise: game_state_statistics, match_events
compress:  game_state_statistics, summaries
author:    user_type, trigger_reason, game_state_statistics, key_event_ledger,
           combined_match_context, match_events, narrative_excerpts
"""
from typing import Protocol

from narrative_engine.core.models import AgentResult


class Agents(Protocol):
    async def summarise(self, variables: dict) -> AgentResult: ...

    async def compress(self, variables: dict) -> AgentResult: ...

    async def author(self, variables: dict) -> AgentResult: ...
