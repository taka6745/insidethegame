"""Deterministic stand-in agents for tests and offline runs. No model calls."""
import asyncio

from narrative_engine.core.models import AgentResult


class FakeAgents:
    def __init__(self, author_delay=0.0):
        self.calls = []  # (agent, variables) in call order
        self.author_delay = author_delay
        self.running = self.max_running = 0

    async def summarise(self, variables):
        self.calls.append(("summarise", variables))
        first = variables["match_events"].splitlines()[0]
        return AgentResult(f"Summary of {first}", "fake", "fake-v1")

    async def compress(self, variables):
        self.calls.append(("compress", variables))
        count = variables["summaries"].count("\n[") + 1
        return AgentResult(f"Compression of {count} summaries", "fake", "fake-v1")

    async def author(self, variables):
        self.calls.append(("author", variables))
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            await asyncio.sleep(self.author_delay)
        finally:
            self.running -= 1
        reason = variables["trigger_reason"].splitlines()[0]
        return AgentResult(f"[{variables['user_type']}] {reason}", "fake", "fake-v1")
