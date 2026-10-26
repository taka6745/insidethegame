"""The four agents on Microsoft Agent Framework, over an OpenAI-compatible chat completions API.
Each role reads OPENAI_<SETTING>_<ROLE>, then OPENAI_<SETTING>, then LOCAL_LLM_* (README.md, Agents).

    python -m narrative_engine.agents.llm     # connection check per role; never prints the key
"""
import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from agent_framework import Agent, Message
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI

from narrative_engine.agents.prompt_source import render_template, shipped
from narrative_engine.core.models import AgentResult, merge_usage

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class LLMError(RuntimeError):
    pass


def load_env(path=ENV_FILE):
    """KEY=value lines into os.environ, without overriding variables already set. A value in matching single or
    double quotes is unquoted, as Docker Compose env files are (a kept quote makes the model id unknown: HTTP 404)."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


def clean_text(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    if len(text) > 1 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    return text


def parse_summary(text):
    """The `summary` string from a JSON reply, tolerating code fences and surrounding text."""
    match = re.search(r"\{.*\}", clean_text(text), re.S)
    if not match:
        raise ValueError("no JSON object in the reply")
    summary = json.loads(match.group(0)).get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("reply has no non-empty 'summary'")
    return summary.strip()


ROLES = ("summary", "compression", "analyst", "author")


@dataclass(frozen=True)
class ModelSettings:
    """One role's model: the deployment (or model) name, its endpoint and the reasoning effort."""
    model: str
    base_url: str
    api_key: str
    effort: str = None

    def recorded(self, answered=None):
        """The model name stored with outputs: Azure's deployment or model, never a local model's id."""
        on_azure = ".azure.com" in self.base_url or ".azure-api.net" in self.base_url
        return (answered or self.model) if on_azure else "local-model"


@dataclass(frozen=True)
class LLMSettings:
    summary: ModelSettings
    compression: ModelSettings
    analyst: ModelSettings
    author: ModelSettings
    timeout: float = 180.0
    retries: int = 4  # by the OpenAI client: rate limits, server errors and dropped connections

    @classmethod
    def from_env(cls):
        load_env()

        def setting(name, role, default=None):
            return (os.environ.get(f"OPENAI_{name}_{role.upper()}") or os.environ.get(f"OPENAI_{name}")
                    or os.environ.get(f"LOCAL_LLM_{name}") or default)

        roles = {}
        for role in ROLES:
            base_url = setting("BASE_URL", role)
            api_key = setting("API_KEY", role, "local" if os.environ.get("LOCAL_LLM_BASE_URL") else None)
            if not (base_url and api_key):
                raise LLMError(f"set OPENAI_BASE_URL and OPENAI_API_KEY (or LOCAL_LLM_BASE_URL) in the environment "
                               f"or {ENV_FILE}")
            if not (model := setting("MODEL", role)):
                raise LLMError(f"set OPENAI_MODEL (or LOCAL_LLM_MODEL) in the environment or {ENV_FILE}")
            roles[role] = ModelSettings(model, base_url.rstrip("/"),
                                        api_key, setting("EFFORT", role))
        return cls(**roles)


def chat_client(model, settings, http_client=None):
    """The only provider-specific code: change this to put an agent on another kind of model API."""
    return OpenAIChatCompletionClient(model.model, async_client=AsyncOpenAI(
        base_url=model.base_url, api_key=model.api_key, timeout=settings.timeout, max_retries=settings.retries,
        http_client=http_client))


def failure(error):
    """What went wrong, without the response body (which can echo part of the key)."""
    while error is not None:
        if status := getattr(error, "status_code", None):
            return f"HTTP {status}"
        if error.__cause__ is None:
            return type(error).__name__
        error = error.__cause__


AGENTS = {"summary": ("minute-summariser", "Summarises one closed match minute"),
          "compression": ("context-compressor", "Merges minute summaries into a shorter block"),
          "analyst": ("match-analyst", "Names the grounded multi-minute patterns and moves the storylines"),
          "author": ("narrative-author", "Writes one audience bucket's narrative step")}


class LLMAgents:
    """`roles` (optional): the user backend's model per role (`GET /model-roles`, edited under /dev/config/models).
    A role with a deployment runs on that deployment at the same endpoint with its effort; an empty one, or an
    unreachable backend, keeps this deployment's environment settings."""

    def __init__(self, settings, http_client=None, roles=None):
        self.settings, self.http_client, self.roles = settings, http_client, roles
        self.clients, self.agents, self.models = [], {}, {}
        for role in AGENTS:
            self._build(role, getattr(settings, role))

    def _build(self, role, model):
        name, description = AGENTS[role]
        client = chat_client(model, self.settings, self.http_client)
        self.clients.append(client)
        self.models[role] = model
        self.agents[role] = Agent(client=client, name=name, description=description,
                                  default_options={"reasoning_effort": model.effort} if model.effort else None)

    async def _apply_roles(self, role):
        if self.roles is None:
            return
        try:
            override = (await self.roles.get())["value"]["engine"][role]
        except Exception:  # unreachable or malformed: keep the current model
            return
        base = getattr(self.settings, role)
        wanted = (ModelSettings(override["deployment"], base.base_url, base.api_key, override.get("effort") or None)
                  if override.get("deployment") else base)
        current = self.models[role]
        if (wanted.model, wanted.effort) != (current.model, current.effort):
            self._build(role, wanted)

    async def aclose(self):
        for client in self.clients:
            await client.client.close()

    async def _run(self, role, messages):
        """One agent run: (text, model that answered, token usage)."""
        await self._apply_roles(role)
        agent = self.agents[role]
        try:
            response = await agent.run(messages)
        except Exception as error:
            raise LLMError(f"{agent.name} failed ({failure(error)})") from None
        usage = response.usage_details
        tokens = {"prompt_tokens": usage.get("input_token_count") or 0,
                  "completion_tokens": usage.get("output_token_count") or 0,
                  "total_tokens": usage.get("total_token_count") or 0,
                  # prompt tokens served from the API's prompt cache (README.md, Agents)
                  "cached_tokens": usage.get("cache_read_input_token_count")
                  or usage.get("prompt/cached_tokens") or 0} if usage else None
        model = self.models[role].recorded(getattr(response.raw_representation, "model", None))
        return response.text or "", model, tokens

    async def _summary(self, role, prompt, variables):
        """A JSON {"summary": ...} reply, asking once more if the first is not valid."""
        messages = [Message("user", [render_template(prompt, variables)])]
        tokens = []
        for attempt in range(2):
            text, used, usage = await self._run(role, messages)
            tokens.append(usage)
            try:
                return AgentResult(parse_summary(text), used, prompt.label, merge_usage(tokens))
            except ValueError as error:
                if attempt:
                    raise LLMError(f"{prompt.label}: invalid reply twice ({error})")
                messages += [Message("assistant", [text]),
                             Message("user", ['Reply with only the JSON object {"summary": "..."}.'])]

    async def summarise(self, variables, prompt=None):
        return await self._summary("summary", prompt or shipped("minute-summary"), variables)

    async def compress(self, variables, prompt=None):
        return await self._summary("compression", prompt or shipped("context-compression"), variables)

    async def analyse(self, variables, prompt=None, feedback=None):
        """The reply text with a JSON object in it (asked once more if there is none); the orchestrator
        checks it with analysis.validator. `feedback` (earlier reply, repair request) continues that
        conversation for the one repair turn."""
        prompt = prompt or shipped("match-analyst")
        messages = conversation(render_template(prompt, variables), feedback)
        tokens = []
        for attempt in range(2):
            text, used, usage = await self._run("analyst", messages)
            tokens.append(usage)
            text = clean_text(text)
            if re.search(r"\{.*\}", text, re.S) or attempt:
                return AgentResult(text, used, prompt.label, merge_usage(tokens))
            messages += [Message("assistant", [text]), Message("user", ["Reply with only the JSON object."])]

    async def author(self, variables, prompt=None, feedback=None):
        """`variables["user_type"]` is the audience framing text (audience.targets.framing); `feedback`
        (earlier excerpt, repair request) asks for the one rewrite the grounding check allows."""
        prompt = prompt or shipped("narrative-author")
        messages = conversation(render_template(prompt, variables), feedback)
        tokens = []
        for _ in range(2):
            text, used, usage = await self._run("author", messages)
            tokens.append(usage)
            if text := clean_text(text):
                return AgentResult(text, used, prompt.label, merge_usage(tokens))
        raise LLMError(f"{prompt.label}: empty reply twice")


def conversation(prompt_text, feedback=None):
    messages = [Message("user", [prompt_text])]
    if feedback:
        previous, request = feedback
        messages += [Message("assistant", [previous]), Message("user", [request])]
    return messages


async def check():
    agents = LLMAgents(LLMSettings.from_env())
    try:
        for role in ROLES:
            text, model, _ = await agents._run(role, "Reply with exactly: connection verified")
            print(f"{agents.agents[role].name}: {model}: {text.strip()}")
    finally:
        await agents.aclose()


if __name__ == "__main__":
    asyncio.run(check())
