"""Agent Framework agents against a mocked chat completions endpoint (no network)."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from narrative_engine.agents.fake import FakeAgents
from narrative_engine.agents.llm import (PLACEHOLDER, PROMPTS, LLMAgents, LLMError, LLMSettings, ModelSettings,
                                         parse_summary, render_template)
from narrative_engine.match_data.fixture import FixtureMatchData
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink, read_notifications

FIXTURES = Path(__file__).parent / "fixtures"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
SECRET = "test-key-not-real"
SETTINGS = LLMSettings(ModelSettings("m-summary", "https://llm.example/v1", SECRET),
                       ModelSettings("m-compress", "https://llm.example/v1", SECRET),
                       ModelSettings("m-author", "https://llm.example/v1", SECRET), retries=4)
NO_WAIT = {"retry-after-ms": "1"}  # the OpenAI client's retry backoff honours this


def reply(content, model="upstream-x", usage=None):
    return httpx.Response(200, json={
        "id": "c1", "object": "chat.completion", "created": 0, "model": model,
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]})


class FakeApi:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, request):
        self.requests.append((request, json.loads(request.content)))
        return self.responses.pop(0)


def agents(api, settings=SETTINGS):
    return LLMAgents(settings, httpx.AsyncClient(transport=httpx.MockTransport(api)))


@pytest.fixture(scope="module")
def real_variables():
    """Variables the engine actually builds for each agent over the synthetic match."""
    fake, store = FakeAgents(), MemoryStore()
    engine = MatchOrchestrator("m", FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS), fake, store,
                               MemorySink(store))

    async def go():
        for _, m in read_notifications(NOTIFICATIONS, "m"):
            if m:
                await engine.handle(m)
    asyncio.run(go())
    return {agent: next(v for a, v in fake.calls if a == agent) for agent in ("summarise", "compress", "author")}


def test_templates_take_exactly_the_engine_variables(real_variables):
    for agent, name in [("summarise", "minute-summary.v1"), ("compress", "context-compression.v1"),
                        ("author", "narrative-author.v2")]:
        placeholders = set(PLACEHOLDER.findall((PROMPTS / f"{name}.txt").read_text()))
        assert placeholders == set(real_variables[agent]), name
        rendered = render_template(name, real_variables[agent])
        assert not PLACEHOLDER.search(rendered.replace('{"summary"', ""))
    with pytest.raises(KeyError):
        render_template("minute-summary.v1", {"match_events": ""})


def test_originals_are_unchanged_and_runtime_keeps_their_wording():
    for original, runtime in [("minute-summary", "minute-summary.v1"), ("narrative-author", "narrative-author.v2")]:
        first_paragraph = (PROMPTS.parents[2] / "docs" / "design" / "example-prompts" / f"{original}.txt").read_text().split("\n\n")[0]
        assert first_paragraph in (PROMPTS / f"{runtime}.txt").read_text()


def test_summary_parses_json_and_records_model_prompt_and_tokens(real_variables):
    api = FakeApi(reply('```json\n{"summary": "Home team (Riverside FC) kept the ball."}\n```'))
    result = asyncio.run(agents(api).summarise(real_variables["summarise"]))
    assert (result.text, result.model, result.promptVersion) == \
           ("Home team (Riverside FC) kept the ball.", "upstream-x", "minute-summary.v1")
    assert result.tokens == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    request, body = api.requests[0]
    assert body["model"] == "m-summary" and request.url == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {SECRET}" and "reasoning_effort" not in body
    assert real_variables["summarise"]["match_events"] in body["messages"][0]["content"]


def test_invalid_json_is_retried_once_then_fails(real_variables):
    api = FakeApi(reply("Riverside kept the ball."), reply('{"summary": "Fixed."}'))
    result = asyncio.run(agents(api).compress(real_variables["compress"]))
    assert result.text == "Fixed." and result.tokens["total_tokens"] == 30
    assert api.requests[1][1]["model"] == "m-compress" and len(api.requests[1][1]["messages"]) == 3
    with pytest.raises(LLMError, match="invalid reply twice"):
        asyncio.run(agents(FakeApi(reply("no"), reply('{"summary": ""}'))).summarise(real_variables["summarise"]))


def test_rate_limits_and_server_errors_are_retried():
    api = FakeApi(httpx.Response(429, headers=NO_WAIT), httpx.Response(503, headers=NO_WAIT),
                  reply('{"summary": "ok"}'))
    assert asyncio.run(agents(api).summarise({"game_state_statistics": "", "match_events": ""})).text == "ok"
    assert len(api.requests) == 3


def test_auth_failures_stop_at_once_without_leaking_the_key():
    api = FakeApi(httpx.Response(410, text="access window ended"))
    with pytest.raises(LLMError) as error:
        asyncio.run(agents(api).summarise({"game_state_statistics": "", "match_events": ""}))
    assert "410" in str(error.value) and SECRET not in str(error.value) and len(api.requests) == 1


def test_author_sends_a_described_user_type_and_cleans_the_reply(real_variables):
    api = FakeApi(reply("   "), reply('<think>plan</think>\n"Mensah scores for Riverside!"'))
    result = asyncio.run(agents(api).author({**real_variables["author"], "user_type": "away:analyst"}))
    assert result.text == "Mensah scores for Riverside!" and result.promptVersion == "narrative-author.v2"
    prompt = api.requests[0][1]["messages"][0]["content"]
    assert "away:analyst (a fan of the away team, analyst experience level)" in prompt
    assert api.requests[0][1]["model"] == "m-author"


def test_parse_summary_tolerates_surrounding_text():
    assert parse_summary('Sure! {"summary": " Even contest. "} Hope that helps') == "Even contest."


def test_each_role_has_its_own_model_effort_and_endpoint(monkeypatch):
    for key in ("OPENAI_MODEL", "OPENAI_EFFORT", "OPENAI_BASE_URL_AUTHOR", "OPENAI_API_KEY_AUTHOR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://foundry.example/openai/v1/")
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("OPENAI_MODEL", "small")
    monkeypatch.setenv("OPENAI_EFFORT_SUMMARY", "minimal")
    monkeypatch.setenv("OPENAI_MODEL_AUTHOR", "smart")
    monkeypatch.setenv("OPENAI_EFFORT_AUTHOR", "medium")
    monkeypatch.setenv("OPENAI_BASE_URL_AUTHOR", "https://other.example/v1")
    settings = LLMSettings.from_env()
    assert settings.summary == ModelSettings("small", "https://foundry.example/openai/v1", SECRET, "minimal")
    assert settings.compression == ModelSettings("small", "https://foundry.example/openai/v1", SECRET, None)
    assert settings.author == ModelSettings("smart", "https://other.example/v1", SECRET, "medium")

    api = FakeApi(reply('{"summary": "s"}'), reply('{"summary": "c"}'), reply("A line."))
    engine = agents(api, settings)
    asyncio.run(engine.summarise({"game_state_statistics": "", "match_events": ""}))
    asyncio.run(engine.compress({"game_state_statistics": "", "summaries": ""}))
    asyncio.run(engine.author({"user_type": "home:simple", "trigger_reason": "", "game_state_statistics": "",
                               "key_event_ledger": "", "combined_match_context": "", "match_events": "",
                               "narrative_excerpts": ""}))
    sent = [(str(r.url), b["model"], b.get("reasoning_effort")) for r, b in api.requests]
    assert sent == [("https://foundry.example/openai/v1/chat/completions", "small", "minimal"),
                    ("https://foundry.example/openai/v1/chat/completions", "small", None),
                    ("https://other.example/v1/chat/completions", "smart", "medium")]
