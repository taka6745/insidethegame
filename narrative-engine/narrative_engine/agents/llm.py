"""The three agents on Microsoft Agent Framework, over an OpenAI-compatible chat completions API
(Foundry's /openai/v1 when deployed, the dev router locally).

Settings come from the environment, or from narrative-engine/.env (ignored by Git). Each role
(SUMMARY, COMPRESSION, AUTHOR) reads OPENAI_<SETTING>_<ROLE> and falls back to OPENAI_<SETTING>,
so one role can move to another model, effort or endpoint on its own:
OPENAI_BASE_URL (includes /v1), OPENAI_API_KEY, OPENAI_MODEL, OPENAI_EFFORT (reasoning_effort,
sent only when set). For example OPENAI_MODEL_AUTHOR=gpt-5 OPENAI_EFFORT_AUTHOR=medium.

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

from narrative_engine.core.models import AgentResult

PROMPTS = Path(__file__).parent / "prompts"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
SUPPORT_TEXT = {"home": "a fan of the home team", "away": "a fan of the away team", "neutral": "a neutral viewer"}


class LLMError(RuntimeError):
    pass


def load_env(path=ENV_FILE):
    """KEY=value lines into os.environ, without overriding variables already set."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def render_template(name, variables):
    """Fill `{name}` placeholders; JSON braces in the template are left alone."""
    text = (PROMPTS / f"{name}.txt").read_text(encoding="utf-8")
    missing = set(PLACEHOLDER.findall(text)) - set(variables)
    if missing:
        raise KeyError(f"{name} needs {sorted(missing)}")
    return PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), text)


def describe_user_type(user_type):
    support, level = user_type.split(":")
    return f"{user_type} ({SUPPORT_TEXT[support]}, {level} experience level)"


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


ROLES = ("summary", "compression", "author")


@dataclass(frozen=True)
class ModelSettings:
    """One role's model: the deployment (or model) name, its endpoint and the reasoning effort."""
    model: str
    base_url: str
    api_key: str
    effort: str = None


@dataclass(frozen=True)
class LLMSettings:
    summary: ModelSettings
    compression: ModelSettings
    author: ModelSettings
    timeout: float = 180.0
    retries: int = 4  # by the OpenAI client: rate limits, server errors and dropped connections

    @classmethod
    def from_env(cls):
        load_env()

        def setting(name, role, default=None):
            return os.environ.get(f"OPENAI_{name}_{role.upper()}") or os.environ.get(f"OPENAI_{name}") or default

        roles = {}
        for role in ROLES:
            base_url, api_key = setting("BASE_URL", role), setting("API_KEY", role)
            if not (base_url and api_key):
                raise LLMError(f"set OPENAI_BASE_URL and OPENAI_API_KEY in the environment or {ENV_FILE}")
            roles[role] = ModelSettings(setting("MODEL", role, "auto:intelligence-chain"), base_url.rstrip("/"),
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
          "author": ("narrative-author", "Writes one audience bucket's narrative step")}


class LLMAgents:
    summary_prompt = "minute-summary.v1"
    compression_prompt = "context-compression.v1"
    author_prompt = "narrative-author.v2"

    def __init__(self, settings, http_client=None):
        self.settings, self.clients, self.agents = settings, [], {}
        for role, (name, description) in AGENTS.items():
            model = getattr(settings, role)
            client = chat_client(model, settings, http_client)
            self.clients.append(client)
            self.agents[role] = Agent(client=client, name=name, description=description,
                                      default_options={"reasoning_effort": model.effort} if model.effort else None)

    async def aclose(self):
        for client in self.clients:
            await client.client.close()

    async def _run(self, role, messages):
        """One agent run: (text, model that answered, token usage)."""
        agent = self.agents[role]
        try:
            response = await agent.run(messages)
        except Exception as error:
            raise LLMError(f"{agent.name} failed ({failure(error)})") from None
        usage = response.usage_details
        tokens = {"prompt_tokens": usage.get("input_token_count") or 0,
                  "completion_tokens": usage.get("output_token_count") or 0,
                  "total_tokens": usage.get("total_token_count") or 0} if usage else None
        model = getattr(response.raw_representation, "model", None) or getattr(self.settings, role).model
        return response.text or "", model, tokens

    async def _summary(self, role, prompt_name, variables):
        """A JSON {"summary": ...} reply, asking once more if the first is not valid."""
        messages = [Message("user", [render_template(prompt_name, variables)])]
        tokens = []
        for attempt in range(2):
            text, used, usage = await self._run(role, messages)
            tokens.append(usage)
            try:
                return AgentResult(parse_summary(text), used, prompt_name, merge_usage(tokens))
            except ValueError as error:
                if attempt:
                    raise LLMError(f"{prompt_name}: invalid reply twice ({error})")
                messages += [Message("assistant", [text]),
                             Message("user", ['Reply with only the JSON object {"summary": "..."}.'])]

    async def summarise(self, variables):
        return await self._summary("summary", self.summary_prompt, variables)

    async def compress(self, variables):
        return await self._summary("compression", self.compression_prompt, variables)

    async def author(self, variables):
        prompt = render_template(self.author_prompt, {**variables, "user_type": describe_user_type(variables["user_type"])})
        tokens = []
        for _ in range(2):
            text, used, usage = await self._run("author", [Message("user", [prompt])])
            tokens.append(usage)
            if text := clean_text(text):
                return AgentResult(text, used, self.author_prompt, merge_usage(tokens))
        raise LLMError(f"{self.author_prompt}: empty reply twice")


def merge_usage(usages):
    usages = [u for u in usages if u]
    if not usages:
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {k: sum(u.get(k) or 0 for u in usages) for k in keys}


async def check():
    agents = LLMAgents(LLMSettings.from_env())
    try:
        for role in ROLES:
            text, model, _ = await agents._run(role, "Reply with exactly: connection verified")
            print(f"{agents.agents[role].name}: {getattr(agents.settings, role).model} -> {model}: {text.strip()}")
    finally:
        await agents.aclose()


if __name__ == "__main__":
    asyncio.run(check())
