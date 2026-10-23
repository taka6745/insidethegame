"""The local fallback decision model: a chat model constrained to a JSON schema of enums (an answer plus a
confidence per question, no free text). One repair turn, then DecisionError. The answer gets its confidence
and the other values share the rest."""
import json
import re

import httpx
from openai import APIStatusError, AsyncOpenAI

from . import Answer, Choice, DecisionError, Decisions, Noul, merge_tokens, recorded_model

SYSTEM = ("You are a classifier. Read the state and answer every question with one of its allowed values and "
          "your confidence (0 to 1) that the value is right. Reply with only the JSON object the schema describes.")


def values(question):
    if isinstance(question, Noul):
        return ["yes", "no"]
    if isinstance(question, Choice):
        return list(question.options)
    return list(question.levels)


def schema(questions):
    properties = {key: {"type": "object", "additionalProperties": False, "required": ["answer", "confidence"],
                        "properties": {"answer": {"type": "string", "enum": values(q)},
                                       "confidence": {"type": "number"}}}  # 0..1, checked by parse
                  for key, q in questions.items()}
    return {"type": "json_schema", "json_schema": {"name": "decisions", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": list(questions), "properties": properties}}}


def describe(key, question):
    lines = [f"{key}: {question.instructions}"]
    if isinstance(question, Noul):
        lines += [f"  yes means: {question.true}"] if question.true else []
        lines += [f"  no means: {question.false}"] if question.false else []
    elif isinstance(question, Choice):
        lines += [f"  {option}" + (f": {text}" if text else "") for option, text in question.options.items()]
    else:
        lines += [f"  level {i}: {level}" for i, level in enumerate(question.levels)]
    return "\n".join(lines)


def spread(chosen, options, confidence):
    rest = (1.0 - confidence) / (len(options) - 1)
    return {str(o): (confidence if o == chosen else rest) for o in options}


def parse(text, questions):
    """The reply → answers; raises ValueError naming the first problem."""
    found = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", text or "", flags=re.S), re.S)
    if not found:
        raise ValueError("no JSON object")
    reply = json.loads(found.group(0))
    answers = {}
    for key, question in questions.items():
        item = reply.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"{key} is missing")
        answer, confidence = item.get("answer"), item.get("confidence")
        allowed = values(question)
        if answer not in allowed:
            raise ValueError(f"{key}.answer must be one of {allowed}")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"{key}.confidence must be a number from 0 to 1")
        confidence = float(confidence)
        if isinstance(question, Noul):
            answers[key] = Answer("noul", probability=confidence if answer == "yes" else 1.0 - confidence)
        elif isinstance(question, Choice):
            answers[key] = Answer("choice", choice=answer, confidence=confidence,
                                  probabilities=spread(answer, allowed, confidence))
        else:
            index = allowed.index(answer)
            answers[key] = Answer("score", score=float(index), confidence=confidence,
                                  probabilities=spread(index, range(len(allowed)), confidence))
    return answers


class LlmClassifierDecisions:
    own_capacity = False  # the agents' model: its calls take a model-gate slot

    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=settings.timeout, transport=transport)
        self.client = AsyncOpenAI(base_url=settings.base_url.rstrip("/"), api_key=settings.api_key or "local",
                                  timeout=settings.timeout, max_retries=settings.retries, http_client=self.http)

    async def aclose(self):
        await self.client.close()

    async def decide(self, state, questions):
        questions = dict(questions)
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "State:\n" + state + "\n\nQuestions:\n"
                     + "\n".join(describe(k, q) for k, q in questions.items())}]
        usages, answered = [], None
        for attempt in range(2):
            try:
                response = await self.client.chat.completions.create(
                    model=self.settings.model, messages=messages, temperature=0, response_format=schema(questions))
            except APIStatusError as error:
                raise DecisionError(f"decision model failed (HTTP {error.status_code})") from None
            except Exception as error:
                raise DecisionError(f"decision model failed ({type(error).__name__})") from None
            answered = getattr(response, "model", None)
            if response.usage:
                usages.append({"prompt_tokens": response.usage.prompt_tokens or 0,
                               "completion_tokens": response.usage.completion_tokens or 0,
                               "total_tokens": response.usage.total_tokens or 0})
            text = response.choices[0].message.content if response.choices else ""
            try:
                answers = parse(text, questions)
            except (ValueError, json.JSONDecodeError) as error:
                if attempt:
                    raise DecisionError(f"decision model: invalid reply twice ({error})") from None
                messages += [{"role": "assistant", "content": text or ""},
                             {"role": "user", "content": f"That reply is invalid: {error}. Reply with only the "
                                                         "JSON object the schema describes."}]
                continue
            return Decisions(answers, recorded_model(self.settings, answered), merge_tokens(usages))
