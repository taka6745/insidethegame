"""The four agents. Each takes the prompt variables named in prompts/*.txt, as strings, and a
prompt_source.Prompt (None = the shipped file).

summarise: game_state_statistics, match_events
compress:  game_state_statistics, summaries
analyse:   analysis_reason, game_state_statistics, key_event_ledger, combined_match_context, match_trends,
           storylines, plus the limits from validator.prompt_limits (reply: JSON, checked by analysis.validator)
author:    user_type (the audience framing text), trigger_reason, game_state_statistics, key_event_ledger,
           combined_match_context, match_events, narrative_excerpts, storylines, match_trends
analyse and author take `feedback` = (earlier reply, repair request) for the one repair turn.
"""
from typing import Protocol

from narrative_engine.core.models import AgentResult


class Agents(Protocol):
    async def summarise(self, variables: dict, prompt=None) -> AgentResult: ...

    async def compress(self, variables: dict, prompt=None) -> AgentResult: ...

    async def analyse(self, variables: dict, prompt=None, feedback=None) -> AgentResult: ...

    async def author(self, variables: dict, prompt=None, feedback=None) -> AgentResult: ...
