"""Microsoft-Decision-1 on Azure AI Foundry over the SystemOne API (README.md, Decisions). The limit is
requests per minute, so DECISION_REQUESTS_PER_MINUTE paces every request of the process and a 429 waits.

    python -m narrative_engine.decisions.systemone   # one smoke call; never prints the key
"""
import asyncio
import json
import time

import httpx

from . import (Answer, Choice, DecisionError, Decisions, DecisionSettings, Noul, Score, merge_tokens,
               recorded_model)


def encode(question):
    if isinstance(question, Noul):
        criteria = {k: v for k, v in (("true", question.true), ("false", question.false)) if v}
        return {"type": "noul", "instructions": question.instructions, **({"criteria": criteria} if criteria else {})}
    if isinstance(question, Choice):
        return {"type": "choice", "instructions": question.instructions, "criteria": dict(question.options)}
    if isinstance(question, Score):
        return {"type": "score", "instructions": question.instructions, "criteria": list(question.levels)}
    raise TypeError(f"not a decision question: {type(question).__name__}")


def unit(value):
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError("probability outside 0..1")
    return value


def decode(question, raw):
    """One SystemOne answer → Answer; raises ValueError when it does not fit the question."""
    if isinstance(question, Noul):
        return Answer("noul", probability=unit(raw["noul"]))
    probabilities = {str(k): unit(v) for k, v in (raw.get("probabilities") or {}).items()}
    if isinstance(question, Choice):
        if raw["choice"] not in question.options:
            raise ValueError("choice outside the options")
        return Answer("choice", choice=raw["choice"], confidence=unit(raw["confidence"]), probabilities=probabilities)
    score = float(raw["score"])
    if not 0 <= score <= len(question.levels) - 1:
        raise ValueError("score outside the levels")
    return Answer("score", score=score, confidence=unit(raw["confidence"]), probabilities=probabilities)


def seconds(retry_after):
    """A numeric retry-after in seconds; 0 when absent or an HTTP date."""
    try:
        return max(float(retry_after or 0), 0.0)
    except ValueError:
        return 0.0


class RequestWindow:
    """At most `per_minute` requests in any 60 seconds; callers wait their turn."""

    def __init__(self, per_minute, clock=time.monotonic):
        self.per_minute, self.clock, self.stamps, self.lock = per_minute, clock, [], asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            while True:
                now = self.clock()
                self.stamps = [t for t in self.stamps if now - t < 60.0]
                if len(self.stamps) < self.per_minute:
                    self.stamps.append(now)
                    return
                await asyncio.sleep(60.0 - (now - self.stamps[0]) + 0.05)


class SystemOneDecisions:
    own_capacity = True  # its own deployment, paced by `window`: it never waits for the agents' model gate

    def __init__(self, settings: DecisionSettings, transport=None):
        self.settings = settings
        headers = {"Content-Type": "application/json"}
        if settings.auth == "api-key":
            headers["api-key"] = settings.api_key
        elif settings.auth == "bearer":
            headers["Authorization"] = f"Bearer {settings.api_key}"
        self.url = settings.base_url.rstrip("/") + "/" + settings.path.lstrip("/")
        self.http = httpx.AsyncClient(timeout=settings.timeout, headers=headers, transport=transport)
        self.window = RequestWindow(settings.requests_per_minute) if settings.requests_per_minute else None

    async def aclose(self):
        await self.http.aclose()

    async def decide(self, state, questions):
        keys = list(questions)
        size = self.settings.max_questions
        chunks = [keys[i:i + size] for i in range(0, len(keys), size)]
        replies = await asyncio.gather(*(self._call(state, {k: questions[k] for k in chunk}) for chunk in chunks))
        answers, models, usages = {}, [], []
        for chunk, (body, usage) in zip(chunks, replies):
            models.append(body.get("model"))
            usages.append(usage)
            returned = body.get("answers") or {}
            if not isinstance(returned, dict):
                raise DecisionError("decision reply: answers is not an object")
            for key in chunk:
                raw = returned.get(key)
                if raw is None:
                    continue  # declined: the caller treats a missing answer as "no"
                try:
                    answers[key] = decode(questions[key], raw)
                except (KeyError, TypeError, ValueError) as error:
                    raise DecisionError(f"decision {key}: invalid answer ({error})") from None
        answered = next((m for m in models if m), None)
        return Decisions(answers, recorded_model(self.settings, answered), merge_tokens(usages))

    async def _call(self, state, questions):
        body = {"state": state, "questions": {k: encode(q) for k, q in questions.items()}}
        if self.settings.model_field:
            body = {self.settings.model_field: self.settings.model, **body}
        delay = 1.0
        for attempt in range(self.settings.retries + 1):
            if self.window:
                await self.window.acquire()
            try:
                response = await self.http.post(self.url, json=body)
            except httpx.HTTPError as error:
                problem = type(error).__name__
            else:
                if response.status_code < 400:
                    try:
                        reply = response.json()
                        usage = reply.get("usage") or {}
                    except (ValueError, AttributeError):
                        raise DecisionError("decision reply is not a JSON object") from None
                    tokens = {"prompt_tokens": usage.get("input_tokens") or 0,
                              "completion_tokens": usage.get("output_tokens") or 0}
                    return reply, {**tokens, "total_tokens": sum(tokens.values())}
                problem = f"HTTP {response.status_code}"
                if response.status_code not in (408, 429) and response.status_code < 500:
                    break
                delay = max(delay, min(seconds(response.headers.get("retry-after")), 60.0))
            if attempt < self.settings.retries:
                await asyncio.sleep(delay)
                delay *= 2
        raise DecisionError(f"decision model failed ({problem})")


async def smoke(env=None):
    """One noul question; prints the probability and the deployment that answered."""
    settings = DecisionSettings.from_env(env)
    model = SystemOneDecisions(settings)
    try:
        result = await model.decide(json.dumps({"home_goals": 2, "away_goals": 0, "minute": 88}),
                                    {"leading": Noul("Is the home team ahead?")})
        print(f"{result.model}: noul={result.answers['leading'].probability:.3f} tokens={result.tokens}")
    finally:
        await model.aclose()


if __name__ == "__main__":
    asyncio.run(smoke())
