"""Microsoft Agent Framework agents using an OpenAI-compatible local model."""
import json
import os
import logging
from contextlib import asynccontextmanager
from typing import Protocol

import httpx
from agent_framework import Agent
from agent_framework.exceptions import AgentFrameworkException
from agent_framework.openai import OpenAIChatClient, OpenAIChatCompletionClient
from openai import AsyncOpenAI, APIStatusError, APIConnectionError

from backend.adapters.usage import UsageTransport


def model_configured():
    """True when the local model's endpoint and model are configured (values are never logged)."""
    return bool(os.getenv("LOCAL_LLM_BASE_URL") and os.getenv("LOCAL_LLM_MODEL"))


@asynccontextmanager
async def openai_client(base_url: str, api_key: str, http_timeout: float,
                        transport: httpx.AsyncBaseTransport | None = None, **options):
    """An OpenAI-compatible client without SDK retries; the workflow decides what to retry."""
    async with httpx.AsyncClient(timeout=http_timeout, transport=transport) as http:
        async with AsyncOpenAI(base_url=base_url, api_key=api_key or "local-development",
                               http_client=http, max_retries=0, **options) as client:
            yield client


ENV = object()  # effort not given: this deployment's LOCAL_LLM_EFFORT

# Agent name -> role in the `models` config table (models/config.ModelRoles, edited under /dev/config/models).
ROLE_OF = {"match_question": "questions", "question_goal": "questions", "question_intent": "questions",
           "development_agent": "questions", "match_replay": "replay", "subscription_planner": "follow_planner"}
_role_models: dict[str, dict] = {}


def set_role_models(roles: dict) -> None:
    """The backend's role overrides, refreshed live by app.watch_models."""
    _role_models.clear()
    _role_models.update(roles)


def role_model(name: str, default_model: str):
    """(model, effort) for an agent: its role's /dev/ deployment and effort when a deployment is set, else this
    deployment's LOCAL_LLM_MODEL and LOCAL_LLM_EFFORT. A role with a deployment but no effort keeps this
    deployment's effort: the Foundry models reject the chat call's temperature 0."""
    role = _role_models.get(ROLE_OF.get(name, name)) or {}
    if role.get("deployment"):
        return role["deployment"], role.get("effort") or os.getenv("LOCAL_LLM_EFFORT") or None
    return default_model, os.getenv("LOCAL_LLM_EFFORT") or None


def chat_client(model: str, client, effort=ENV):
    """A chat model answers over Chat Completions. A reasoning model (an effort, e.g. gpt-6.1-sol on Azure AI
    Foundry) goes over the Responses API, the only one where it takes function tools with reasoning."""
    if (os.getenv("LOCAL_LLM_EFFORT") if effort is ENV else effort):
        return OpenAIChatClient(model=model, async_client=client)
    return OpenAIChatCompletionClient(model=model, async_client=client)


def chat_options(max_tokens: int, effort=ENV) -> dict:
    """Model call options. A chat model gets temperature 0. A reasoning model rejects temperature, takes a reasoning
    effort, and counts its reasoning against max_tokens, so it gets LOCAL_LLM_REASONING_TOKENS more."""
    effort = os.getenv("LOCAL_LLM_EFFORT") if effort is ENV else effort
    if not effort:
        return {"temperature": 0, "max_tokens": max_tokens}
    return {"reasoning": {"effort": effort},
            "max_tokens": max_tokens + int(os.getenv("LOCAL_LLM_REASONING_TOKENS", "8000"))}

class ModelError(RuntimeError):
    def __init__(self, message: str, *, reason="model_error", retryable=True):
        super().__init__(message)
        self.reason, self.retryable = reason, retryable


class JsonModel(Protocol):
    async def complete(self, system: str, payload: dict, *, response_schema: dict | None = None) -> dict: ...


class LocalJsonModel:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 120,
                 transport: httpx.AsyncBaseTransport | None = None, *, name="development_agent"):
        self.base_url = base_url.rstrip("/")
        self.model, self.api_key = model, api_key
        # Usage counting only reads token totals; it never records the model or provider.
        self.timeout, self.transport, self.name = timeout, transport or UsageTransport(), name

    @classmethod
    def from_env(cls, *, name="development_agent"):
        url, model = os.getenv("LOCAL_LLM_BASE_URL"), os.getenv("LOCAL_LLM_MODEL")
        if not url or not model:
            raise ModelError("Configure LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL for local model mode")
        return cls(url, model, os.getenv("LOCAL_LLM_API_KEY", ""),
                   float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "120")), name=name)

    async def complete(self, system: str, payload: dict, *, response_schema: dict | None = None) -> dict:
        try:
            async with openai_client(self.base_url, self.api_key, self.timeout, self.transport,
                                     timeout=self.timeout) as client:
                model, effort = role_model(self.name, self.model)
                agent = Agent(name=self.name, instructions=system,
                              client=chat_client(model, client, effort),
                              default_options=chat_options(3000, effort))
                # Each call is stateless. The workflow carries only the goal and
                # validation feedback; no conversation is shared between viewers.
                options = {"response_format": response_schema} if response_schema is not None else {}
                response = await agent.run(json.dumps(payload), options=options)
                if response.finish_reason == "length":
                    raise ModelError("Local model output was truncated", reason="truncated_output")
                content = response.text
                if not isinstance(content, str) or len(content) > 30000:
                    raise ValueError("Invalid response content")
                content = content.strip()
                if content.startswith("```json\n") and content.endswith("```"):
                    content = content[8:-3].strip()
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError("Expected a JSON object")
                return result
        except AgentFrameworkException as exc:
            # SDKs wrap transport exceptions. Inspect types, never log exception
            # messages: those can contain endpoints, credentials or provider bodies.
            cause = exc
            while cause.__cause__ is not None and not isinstance(cause, (APIStatusError, APIConnectionError)):
                cause = cause.__cause__
            if isinstance(cause, APIStatusError):
                status = cause.status_code
                raise ModelError("Local model request failed", reason=f"http_{status}",
                                 retryable=status in {408, 429} or status >= 500) from None
            reason = "transport_error" if isinstance(cause, APIConnectionError) else "invalid_json"
            logging.getLogger(__name__).warning("Local model failure: reason=%s", reason)
            raise ModelError("Local model request failed or returned invalid JSON", reason=reason) from None
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            logging.getLogger(__name__).warning("Local model returned an invalid JSON object")
            raise ModelError("Local model request failed or returned invalid JSON", reason="invalid_json") from None
