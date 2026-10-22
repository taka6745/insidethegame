"""Decision models: bounded classifiers that answer typed questions about a state, with no free text.

A question is `Noul` (yes/no → probability of yes), `Choice` (one of fixed options) or `Score` (a level on a
scale, low → high). Story follows ask them on each minute recap, key event and storyline update to decide
whether a followed story moved (follows/; the state is the rendered subscription-decision prompt), and the
author grounding check asks whether a sentence claims a cause or an intent the evidence does not support
(analysis/validator.claim_reasons).

Adapters behind one protocol, chosen by DECISION_PROVIDER:
- `systemone`: Microsoft-Decision-1 on Azure AI Foundry (SystemOne API; TypeSafe-compatible envelope).
- `llm`: a chat model constrained to a JSON schema of enums, with one repair turn (the local fallback).
Test doubles: devtools/fake_decisions.py.
"""
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol, Union


class DecisionError(RuntimeError):
    """The decision model failed or answered outside the question's options (never carries a response body)."""


@dataclass(frozen=True)
class Noul:
    instructions: str
    true: Optional[str] = None   # what makes the answer yes
    false: Optional[str] = None  # what makes it no


@dataclass(frozen=True)
class Choice:
    instructions: str
    options: Mapping[str, Optional[str]]  # option label -> description (None: the label says it all)

    def __post_init__(self):
        if len(self.options) < 2:
            raise ValueError("a choice needs at least two options")


@dataclass(frozen=True)
class Score:
    instructions: str
    levels: tuple  # level descriptions, lowest first; the answer is a level index

    def __post_init__(self):
        if not 2 <= len(self.levels) <= 10 or len(set(self.levels)) != len(self.levels):
            raise ValueError("a score needs 2 to 10 distinct levels")


Question = Union[Noul, Choice, Score]


@dataclass(frozen=True)
class Answer:
    """`noul`: probability of yes. `choice`: the option. `score`: the level index (a float: Decision-1 may answer
    between levels). `probabilities` maps each option, or level index as a string, to its probability."""
    type: str
    probability: Optional[float] = None
    choice: Optional[str] = None
    score: Optional[float] = None
    confidence: Optional[float] = None
    probabilities: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Decisions:
    answers: Mapping[str, Answer]  # by question key; a key the model declined to answer is missing
    model: Optional[str] = None    # Azure deployment or model that answered; "local-model" off Azure
    tokens: Optional[dict] = None  # prompt_tokens, completion_tokens, total_tokens


class DecisionModel(Protocol):
    async def decide(self, state: str, questions: Mapping[str, Question]) -> Decisions: ...

    async def aclose(self) -> None: ...


PROVIDERS = ("systemone", "llm")


@dataclass(frozen=True)
class DecisionSettings:
    """DECISION_* settings. `path`, `auth` and `model_field` make the SystemOne envelope configurable:
    the body is {model_field: model, "state", "questions"} (an empty model_field leaves the model out)."""
    provider: str
    base_url: str
    api_key: str = ""
    model: str = ""
    path: str = "/providers/microsoft/v1/systemone"
    auth: str = "api-key"           # api-key | bearer | none
    model_field: str = "model"
    timeout: float = 20.0
    retries: int = 2                # 429 and 5xx, with backoff
    max_questions: int = 1          # questions per request; larger batches are split (set from config)
    requests_per_minute: int = 0    # client-side pacing to the deployment's rate limit (0: none)

    def __post_init__(self):
        if self.provider not in PROVIDERS:
            raise ValueError(f"DECISION_PROVIDER must be one of {PROVIDERS}")
        if self.auth not in ("api-key", "bearer", "none"):
            raise ValueError("DECISION_AUTH must be api-key, bearer or none")
        if not self.base_url:
            raise ValueError("set DECISION_BASE_URL")
        if self.max_questions < 1 or self.retries < 0 or self.timeout <= 0 or self.requests_per_minute < 0:
            raise ValueError("DECISION_MAX_QUESTIONS ≥ 1, DECISION_RETRIES ≥ 0, DECISION_TIMEOUT > 0 and "
                             "DECISION_REQUESTS_PER_MINUTE ≥ 0")

    @classmethod
    def from_env(cls, env=None):
        """DECISION_PROVIDER (systemone | llm; default systemone when DECISION_BASE_URL is set, else the llm
        fallback on the agents' model), DECISION_BASE_URL, DECISION_API_KEY, DECISION_MODEL, DECISION_PATH,
        DECISION_AUTH, DECISION_MODEL_FIELD, DECISION_TIMEOUT, DECISION_RETRIES, DECISION_MAX_QUESTIONS,
        DECISION_REQUESTS_PER_MINUTE. The llm
        provider falls back to the agents' OPENAI_*_DECISION, OPENAI_* and LOCAL_LLM_* settings."""
        env = os.environ if env is None else env
        provider = env.get("DECISION_PROVIDER") or ("systemone" if env.get("DECISION_BASE_URL") else "llm")

        def get(name, *fallbacks, default=""):
            names = [f"DECISION_{name}"] + ([f"OPENAI_{f}_DECISION" for f in fallbacks] + [f"OPENAI_{f}" for f in fallbacks]
                                            + [f"LOCAL_LLM_{f}" for f in fallbacks] if provider == "llm" else [])
            return next((env[n] for n in names if env.get(n)), default)

        typed = {"timeout": float, "retries": int, "max_questions": int, "requests_per_minute": int}
        extra = {k: typed[k](env[f"DECISION_{k.upper()}"]) for k in typed if env.get(f"DECISION_{k.upper()}")}
        extra |= {k: env[f"DECISION_{k.upper()}"] for k in ("path", "auth", "model_field")
                  if env.get(f"DECISION_{k.upper()}") is not None}
        return cls(provider, get("BASE_URL", "BASE_URL"), get("API_KEY", "API_KEY"), get("MODEL", "MODEL"), **extra)


def from_settings(settings, transport=None) -> DecisionModel:
    if settings.provider == "systemone":
        from .systemone import SystemOneDecisions
        return SystemOneDecisions(settings, transport=transport)
    from .llm import LlmClassifierDecisions
    return LlmClassifierDecisions(settings, transport=transport)


def merge_tokens(usages):
    usages = [u for u in usages if u]
    if not usages:
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {k: sum(u.get(k) or 0 for u in usages) for k in keys}


def recorded_model(settings, answered=None):
    """The model stored with outputs: an Azure deployment's name, never a local model's id."""
    on_azure = any(host in settings.base_url for host in (".azure.com", ".azure-api.net"))
    return (answered or settings.model or None) if on_azure else "local-model"
