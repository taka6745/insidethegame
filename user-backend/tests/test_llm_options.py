"""Model request shape: a chat model over Chat Completions with temperature 0; a reasoning model (LOCAL_LLM_EFFORT)
over the Responses API with a reasoning effort and no temperature (gpt-6.1-sol takes function tools only there)."""
from agent_framework.openai import OpenAIChatClient, OpenAIChatCompletionClient
from openai import AsyncOpenAI

from backend.adapters.llm import chat_client, chat_options
from backend.services.questions import _chain

CLIENT = AsyncOpenAI(base_url="http://model.invalid/v1", api_key="test")


def test_chat_model_keeps_chat_completions_and_temperature(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_EFFORT", raising=False)
    assert chat_options(1600) == {"temperature": 0, "max_tokens": 1600}
    assert isinstance(chat_client("m", CLIENT), OpenAIChatCompletionClient)


def test_reasoning_model_uses_responses_with_effort_and_no_temperature(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_EFFORT", "low")
    monkeypatch.setenv("LOCAL_LLM_REASONING_TOKENS", "100")
    assert chat_options(1600) == {"reasoning": {"effort": "low"}, "max_tokens": 1700}
    client = chat_client("m", CLIENT)
    assert isinstance(client, OpenAIChatClient) and not isinstance(client, OpenAIChatCompletionClient)


def test_failure_log_names_the_cause():
    try:
        try:
            raise ValueError("Function tools with reasoning_effort are not supported")
        except ValueError as cause:
            raise RuntimeError("") from cause
    except RuntimeError as exc:
        assert [str(e) for e in _chain(exc)] == ["", "Function tools with reasoning_effort are not supported"]


def test_failure_log_stops_where_the_adapter_hid_the_provider_body():
    try:
        try:
            raise ValueError("provider body")
        except ValueError:
            raise RuntimeError("Local model request failed") from None
    except RuntimeError as exc:
        assert [str(e) for e in _chain(exc)] == ["Local model request failed"]
