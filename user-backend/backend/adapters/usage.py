"""Per-question model usage: token counts and calls only, never which model or provider served them."""
import json
from contextvars import ContextVar
from dataclasses import asdict, dataclass

import httpx


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0


_current: ContextVar[Usage | None] = ContextVar("model_usage", default=None)


def start_usage() -> Usage:
    """Collect usage of every model call made from now on in this request's task and its children."""
    usage = Usage()
    _current.set(usage)
    return usage


def record(content: bytes):
    usage = _current.get()
    if usage is None:
        return
    usage.calls += 1
    try:
        counts = json.loads(content).get("usage") or {}
    except (ValueError, AttributeError):
        return
    # Chat Completions name them prompt/completion tokens; the Responses API input/output tokens.
    usage.input_tokens += int(counts.get("prompt_tokens") or counts.get("input_tokens") or 0)
    usage.output_tokens += int(counts.get("completion_tokens") or counts.get("output_tokens") or 0)


class UsageTransport(httpx.AsyncBaseTransport):
    """Reads the OpenAI-compatible `usage` block from each completion response."""

    def __init__(self, inner=lambda: httpx.AsyncHTTPTransport(retries=0)):
        self.inner = inner

    async def handle_async_request(self, request):
        # Clients are created per call and closed afterwards, so each request gets its own pool.
        async with self.inner() as transport:
            response = await transport.handle_async_request(request)
            content = await response.aread()
        record(content)
        return response


def as_dict(usage: Usage, seconds: float) -> dict:
    return {**asdict(usage), "seconds": round(seconds, 2)}
