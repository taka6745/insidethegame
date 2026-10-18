"""Bounded, ephemeral clarification history for the single-process development lab."""
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from backend.domain import RuleError


@dataclass
class Conversation:
    run_id: str
    messages: list[dict[str, str]]
    expires_at: float


class PlanConversations:
    def __init__(self, *, clock=monotonic, ttl=900, capacity=100):
        self.clock, self.ttl, self.capacity = clock, ttl, capacity
        self._items: dict[str, Conversation] = {}

    def history(self, identifier, run_id):
        self._prune()
        if identifier is None:
            return []
        item = self._items.get(identifier)
        if item is None or item.run_id != run_id:
            raise RuleError("conversation_expired", "This request expired. Start a new request.", 409)
        # Keep the original intent; never silently truncate it out of the context.
        if len(item.messages) >= 6:
            raise RuleError("conversation_limit", "Start a new request with the details you have clarified.", 409)
        return [dict(message) for message in item.messages]

    def save(self, identifier, run_id, history, prompt, reply):
        self._prune()
        messages = history + [{"role": "user", "content": prompt},
                              {"role": "assistant", "content": reply}]
        if (len(messages) > 6 or sum(len(item["content"]) for item in messages) > 6000
                or any(not 1 <= len(item["content"]) <= 2000 for item in messages)):
            raise RuleError("conversation_limit", "Start a new request with the details you have clarified.", 409)
        identifier = identifier or str(uuid4())
        if identifier not in self._items and len(self._items) >= self.capacity:
            oldest = min(self._items, key=lambda key: self._items[key].expires_at)
            del self._items[oldest]
        self._items[identifier] = Conversation(run_id, messages, self.clock() + self.ttl)
        return identifier

    def clear(self):
        self._items.clear()

    def _prune(self):
        now = self.clock()
        self._items = {key: item for key, item in self._items.items() if item.expires_at > now}
