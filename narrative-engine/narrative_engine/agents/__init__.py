"""The four agents. Each takes its prompt's variables (prompts/*.txt) as strings and a prompt_source.Prompt
(None = the shipped file); analyse and author also take `feedback` = (earlier reply, repair request).
Variables per agent: docs/components/agents.md."""
from typing import Protocol

from narrative_engine.core.models import AgentResult


class Agents(Protocol):
    async def summarise(self, variables: dict, prompt=None) -> AgentResult: ...

    async def compress(self, variables: dict, prompt=None) -> AgentResult: ...

    async def analyse(self, variables: dict, prompt=None, feedback=None) -> AgentResult: ...

    async def author(self, variables: dict, prompt=None, feedback=None) -> AgentResult: ...
