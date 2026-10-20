import asyncio
import json

import httpx

from backend.adapters.usage import UsageTransport, as_dict, start_usage


def test_usage_counts_tokens_and_calls_per_question_without_model_identity():
    def reply(request):
        return httpx.Response(200, json={"model": "served-model", "usage": {"prompt_tokens": 1200, "completion_tokens": 300}})

    async def run():
        usage = start_usage()
        async with httpx.AsyncClient(transport=UsageTransport(lambda: httpx.MockTransport(reply))) as client:
            await asyncio.gather(client.post("http://model/v1/chat/completions", json={}),
                                 client.post("http://model/v1/chat/completions", json={}))
        return usage

    summary = as_dict(asyncio.run(run()), 4.236)
    assert summary == {"input_tokens": 2400, "output_tokens": 600, "calls": 2, "seconds": 4.24}
    assert "served-model" not in json.dumps(summary)


def test_calls_outside_a_question_are_not_counted():
    async def run():
        async with httpx.AsyncClient(transport=UsageTransport(lambda: httpx.MockTransport(
                lambda request: httpx.Response(200, json={"usage": {"prompt_tokens": 9}})))) as client:
            await client.post("http://model/v1/chat/completions", json={})
    asyncio.run(run())  # No active question: nothing to record, nothing raised.
