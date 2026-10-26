"""Agent Framework agents against a mocked chat completions endpoint (no network)."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from doubles.fake_agents import FakeAgents
from narrative_engine.agents.llm import (LLMAgents, LLMError, LLMSettings, ModelSettings, load_env, parse_summary,
                                         render_template)
from narrative_engine.agents.prompt_source import PLACEHOLDER, PROMPTS, Prompt, shipped
from doubles.fixture_data import FixtureMatchData
from narrative_engine.core.orchestrator import MatchOrchestrator
from doubles.targets import StaticTargets, default_targets
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink, read_notifications

FIXTURES = Path(__file__).parent / "fixtures"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
SECRET = "test-key-not-real"
SETTINGS = LLMSettings(ModelSettings("m-summary", "https://llm.example/v1", SECRET),
                       ModelSettings("m-compress", "https://llm.example/v1", SECRET),
                       ModelSettings("m-analyst", "https://llm.example/v1", SECRET),
                       ModelSettings("m-author", "https://llm.example/v1", SECRET), retries=4)
NO_WAIT = {"retry-after-ms": "1"}  # the API client's retry backoff honours this


def reply(content, model="example-model", usage=None):
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
                               MemorySink(store), targets=StaticTargets(default_targets()))

    async def go():
        for _, m in read_notifications(NOTIFICATIONS, "m"):
            if m:
                await engine.handle(m)
    asyncio.run(go())
    return {agent: next(v for a, v in fake.calls if a == agent) for agent in ("summarise", "compress", "author")}


def test_templates_take_exactly_the_engine_variables(real_variables):
    for agent, role in [("summarise", "minute-summary"), ("compress", "context-compression"),
                        ("author", "narrative-author")]:
        prompt = shipped(role)
        placeholders = set(PLACEHOLDER.findall(prompt.template))
        assert placeholders == set(real_variables[agent]) - {"bucket_id"}, prompt.label
        rendered = render_template(prompt, real_variables[agent])
        assert not PLACEHOLDER.search(rendered.replace('{"summary"', ""))
    assert (shipped("narrative-author").label, shipped("minute-summary").label) == \
        ("narrative-author.v8", "minute-summary.v3")
    analyst = set(PLACEHOLDER.findall(shipped("match-analyst").template))
    assert analyst == {"analysis_reason", "game_state_statistics", "key_event_ledger", "combined_match_context",
                       "match_trends", "storylines", "max_observations", "max_evidence", "confidence_levels",
                       "short_windows", "short_window_levels"}
    with pytest.raises(KeyError):
        render_template(shipped("minute-summary"), {"match_events": ""})


def test_originals_are_unchanged_and_runtime_keeps_their_wording():
    for original, runtime in [("minute-summary", "minute-summary.v1"), ("minute-summary", "minute-summary.v2"),
                              ("minute-summary", "minute-summary.v3"), ("context-compression", "context-compression.v2"),
                              ("narrative-author", "narrative-author.v2"), ("narrative-author", "narrative-author.v3"),
                              ("narrative-author", "narrative-author.v4"), ("narrative-author", "narrative-author.v5"),
                              ("narrative-author", "narrative-author.v6"), ("narrative-author", "narrative-author.v7"),
                              ("narrative-author", "narrative-author.v8")]:
        first_paragraph = (PROMPTS.parents[2] / "docs" / "design" / "example-prompts" / f"{original}.txt").read_text().split("\n\n")[0]
        assert first_paragraph in (PROMPTS / f"{runtime}.txt").read_text()


def test_summary_parses_json_and_records_model_prompt_and_tokens(real_variables):
    api = FakeApi(reply('```json\n{"summary": "Home team (Riverside FC) kept the ball."}\n```', usage={
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "prompt_tokens_details": {"cached_tokens": 8}}))
    result = asyncio.run(agents(api).summarise(real_variables["summarise"]))
    assert (result.text, result.model, result.promptVersion) == \
           ("Home team (Riverside FC) kept the ball.", "local-model", "minute-summary.v3")  # not Azure: no model id
    assert result.tokens == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cached_tokens": 8}
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


def test_author_sends_the_audience_framing_and_cleans_the_reply(real_variables):
    api = FakeApi(reply("   "), reply('<think>plan</think>\n"Mensah scores for Riverside!"'))
    result = asyncio.run(agents(api).author(real_variables["author"]))
    assert result.text == "Mensah scores for Riverside!" and result.promptVersion == "narrative-author.v8"
    prompt = api.requests[0][1]["messages"][0]["content"]
    assert real_variables["author"]["user_type"] in prompt and "Home team: Riverside FC." in prompt
    edited = Prompt("narrative-author", "narrative-author@4", "Audience: {user_type}. Reason: {trigger_reason}.")
    api = FakeApi(reply("Edited."))
    assert asyncio.run(agents(api).author(real_variables["author"], edited)).promptVersion == "narrative-author@4"
    assert api.requests[0][1]["messages"][0]["content"].startswith("Audience: Audience bucket ")
    assert api.requests[0][1]["model"] == "m-author"


def test_analyst_asks_once_more_for_json_then_returns_the_reply_for_the_validator():
    variables = {k: "" for k in ("analysis_reason", "game_state_statistics", "key_event_ledger",
                                 "combined_match_context", "match_trends", "storylines", "max_observations",
                                 "max_evidence", "confidence_levels", "short_windows", "short_window_levels")}
    api = FakeApi(reply("Riverton Rovers look strong."), reply('```json\n{"observations": []}\n```'))
    result = asyncio.run(agents(api).analyse(variables))
    assert result.text.endswith("```") and '{"observations": []}' in result.text
    assert result.promptVersion == "match-analyst.v4" and api.requests[0][1]["model"] == "m-analyst"
    assert len(api.requests[1][1]["messages"]) == 3
    api = FakeApi(reply("no"), reply("still no"))
    assert asyncio.run(agents(api).analyse(variables)).text == "still no"  # the validator rejects it


def test_parse_summary_tolerates_surrounding_text():
    assert parse_summary('Sure! {"summary": " Even contest. "} Hope that helps') == "Even contest."


def test_each_role_has_its_own_model_effort_and_endpoint(monkeypatch):
    for key in ("OPENAI_MODEL", "OPENAI_EFFORT", "OPENAI_BASE_URL_AUTHOR", "OPENAI_API_KEY_AUTHOR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example/v1/")
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("OPENAI_MODEL", "small")
    monkeypatch.setenv("OPENAI_EFFORT_SUMMARY", "minimal")
    monkeypatch.setenv("OPENAI_MODEL_AUTHOR", "smart")
    monkeypatch.setenv("OPENAI_EFFORT_AUTHOR", "medium")
    monkeypatch.setenv("OPENAI_BASE_URL_AUTHOR", "https://other.example/v1")
    settings = LLMSettings.from_env()
    assert settings.summary == ModelSettings("small", "https://llm.example/v1", SECRET, "minimal")
    assert settings.compression == ModelSettings("small", "https://llm.example/v1", SECRET, None)
    assert settings.author == ModelSettings("smart", "https://other.example/v1", SECRET, "medium")

    api = FakeApi(reply('{"summary": "s"}'), reply('{"summary": "c"}'), reply("A line."))
    engine = agents(api, settings)
    asyncio.run(engine.summarise({"game_state_statistics": "", "match_events": ""}))
    asyncio.run(engine.compress({"game_state_statistics": "", "summaries": ""}))
    asyncio.run(engine.author({"user_type": "home:simple", "trigger_reason": "", "game_state_statistics": "",
                               "key_event_ledger": "", "combined_match_context": "", "match_events": "",
                               "narrative_excerpts": "", "storylines": "", "match_trends": ""}))
    sent = [(str(r.url), b["model"], b.get("reasoning_effort")) for r, b in api.requests]
    assert sent == [("https://llm.example/v1/chat/completions", "small", "minimal"),
                    ("https://llm.example/v1/chat/completions", "small", None),
                    ("https://other.example/v1/chat/completions", "smart", "medium")]


def test_the_local_model_settings_are_the_fallback(monkeypatch):
    for name in ("BASE_URL", "API_KEY", "MODEL", "EFFORT"):
        for suffix in ("", "_SUMMARY", "_COMPRESSION", "_ANALYST", "_AUTHOR"):
            monkeypatch.delenv(f"OPENAI_{name}{suffix}", raising=False)
    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://local-model.example/v1/")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "local-model")
    settings = LLMSettings.from_env()
    assert settings.author == ModelSettings("local-model", "http://local-model.example/v1", "local", None)
    monkeypatch.setenv("LOCAL_LLM_API_KEY", SECRET)
    monkeypatch.setenv("OPENAI_MODEL_AUTHOR", "other")
    settings = LLMSettings.from_env()
    assert settings.summary.api_key == SECRET and settings.author.model == "other"


def test_env_file_values_are_unquoted_like_compose(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("A_MODEL='single'\nB_MODEL=\"double\"\nC_MODEL=plain\nD_MODEL='\n", encoding="utf-8")
    for name in "ABCD":
        monkeypatch.delenv(f"{name}_MODEL", raising=False)
    load_env(env)
    import os
    assert [os.environ[f"{n}_MODEL"] for n in "ABCD"] == ["single", "double", "plain", "'"]


def test_only_azure_model_names_are_recorded():
    azure = ModelSettings("gpt-5-mini", "https://itg.openai.azure.com/openai/v1", SECRET)
    api = FakeApi(reply('{"summary": "s"}', model="gpt-5-mini-2025-08-07"))
    result = asyncio.run(agents(api, LLMSettings(azure, azure, azure, azure)).summarise(
        {"game_state_statistics": "", "match_events": ""}))
    assert result.model == "gpt-5-mini-2025-08-07"
    assert ModelSettings("some-local-id", "http://router:4000/v1", "local").recorded("some-local-id") == "local-model"
