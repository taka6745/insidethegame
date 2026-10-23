"""Decision adapters over httpx.MockTransport: envelope, auth, batching, retries, constrained JSON and repair."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from narrative_engine.core.gate import ModelGate
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.decisions import (Choice, DecisionError, DecisionSettings, Noul, Score, from_settings)
from doubles.fake_decisions import FakeDecisions

AZURE = "https://example.cognitiveservices.azure.com/"
QUESTIONS = {"moved": Noul("Did the followed story move?", true="It changed", false="Nothing new"),
             "kind": Choice("What changed?", {"momentum": None, "result": "The score changed"}),
             "size": Score("How much?", ("none", "some", "a lot"))}


def run(coro):
    return asyncio.run(coro)


def settings(**overrides):
    env = {"DECISION_PROVIDER": "systemone", "DECISION_BASE_URL": AZURE, "DECISION_API_KEY": "k",
           "DECISION_MODEL": "decision-1", **overrides}
    return DecisionSettings.from_env(env)


def systemone_reply(body):
    answers = {}
    for key, q in body["questions"].items():
        answers[key] = {"noul": {"type": "noul", "noul": 0.81},
                        "choice": {"type": "choice", "choice": "result", "confidence": 0.7,
                                   "probabilities": {"momentum": 0.3, "result": 0.7}},
                        "score": {"type": "score", "score": 1.4, "confidence": 0.6, "legend": q.get("criteria"),
                                  "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5}}}[q["type"]]
    return {"model": "Microsoft-Decision-1", "answers": answers, "usage": {"input_tokens": 40, "output_tokens": 2}}


def test_systemone_envelope_auth_and_answers():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=systemone_reply(json.loads(request.content)))

    model = from_settings(settings(DECISION_MAX_QUESTIONS="8"), httpx.MockTransport(handler))
    result = run(model.decide("STATE", QUESTIONS))
    request, = seen
    assert str(request.url) == AZURE + "providers/microsoft/v1/systemone"
    assert request.headers["api-key"] == "k" and "authorization" not in request.headers
    body = json.loads(request.content)
    assert body == {"model": "decision-1", "state": "STATE", "questions": {
        "moved": {"type": "noul", "instructions": "Did the followed story move?",
                  "criteria": {"true": "It changed", "false": "Nothing new"}},
        "kind": {"type": "choice", "instructions": "What changed?", "criteria": {"momentum": None, "result": "The score changed"}},
        "size": {"type": "score", "instructions": "How much?", "criteria": ["none", "some", "a lot"]}}}
    assert result.answers["moved"].probability == 0.81
    assert result.answers["kind"].choice == "result" and result.answers["kind"].confidence == 0.7
    assert result.answers["size"].score == 1.4
    assert result.model == "Microsoft-Decision-1"
    assert result.tokens == {"prompt_tokens": 40, "completion_tokens": 2, "total_tokens": 42}


def test_systemone_path_auth_and_model_field_come_from_settings():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=systemone_reply(json.loads(request.content)))

    model = from_settings(settings(DECISION_PATH="/v2/decide", DECISION_AUTH="bearer", DECISION_MODEL_FIELD=""),
                          httpx.MockTransport(handler))
    run(model.decide("S", {"moved": QUESTIONS["moved"]}))
    assert seen[0].url.path == "/v2/decide" and seen[0].headers["authorization"] == "Bearer k"
    assert "model" not in json.loads(seen[0].content)


def test_systemone_splits_batches_and_skips_declined_answers():
    sizes = []

    def handler(request):
        body = json.loads(request.content)
        sizes.append(len(body["questions"]))
        reply = systemone_reply(body)
        reply["answers"].pop("q3", None)  # declined
        return httpx.Response(200, json=reply)

    model = from_settings(settings(DECISION_MAX_QUESTIONS="2"), httpx.MockTransport(handler))
    result = run(model.decide("S", {f"q{i}": Noul(f"Question {i}?") for i in range(5)}))
    assert sorted(sizes) == [1, 2, 2]
    assert set(result.answers) == {"q0", "q1", "q2", "q4"}
    assert result.tokens["total_tokens"] == 3 * 42


def test_systemone_retries_rate_limits_then_fails_without_the_body(monkeypatch):
    calls = []

    async def no_sleep(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    def handler(request):
        calls.append(1)
        return httpx.Response(429 if len(calls) < 3 else 401, text="secret-echo",
                              headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})  # an HTTP date: backoff

    model = from_settings(settings(DECISION_RETRIES="4"), httpx.MockTransport(handler))
    with pytest.raises(DecisionError) as error:
        run(model.decide("S", {"moved": QUESTIONS["moved"]}))
    assert len(calls) == 3 and "HTTP 401" in str(error.value) and "secret" not in str(error.value)


def test_the_request_window_paces_requests_to_the_per_minute_limit(monkeypatch):
    from narrative_engine.decisions.systemone import RequestWindow
    now, waits = [0.0], []

    async def wait(seconds):
        waits.append(round(seconds, 2))
        now[0] += seconds

    monkeypatch.setattr(asyncio, "sleep", wait)
    window = RequestWindow(2, clock=lambda: now[0])

    async def go():
        for _ in range(3):
            await window.acquire()
            now[0] += 1.0
    run(go())
    assert waits == [58.05] and len(window.stamps) == 2  # the third waits until the first is a minute old
    assert DecisionSettings.from_env({"DECISION_BASE_URL": AZURE, "DECISION_REQUESTS_PER_MINUTE": "9"}) \
        .requests_per_minute == 9


def test_systemone_rejects_answers_outside_the_question():
    def handler(request):
        return httpx.Response(200, json={"answers": {"kind": {"type": "choice", "choice": "other", "confidence": 1,
                                                              "probabilities": {}}}})

    model = from_settings(settings(), httpx.MockTransport(handler))
    with pytest.raises(DecisionError):
        run(model.decide("S", {"kind": QUESTIONS["kind"]}))


def test_systemone_answers_that_are_not_an_object_are_a_decision_error():
    model = from_settings(settings(), httpx.MockTransport(lambda request: httpx.Response(200, json={"answers": ["kind"]})))
    with pytest.raises(DecisionError, match="not an object"):
        run(model.decide("S", {"kind": QUESTIONS["kind"]}))


def chat(content, model="local"):
    return {"id": "c", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def llm_settings():
    return DecisionSettings.from_env({"DECISION_PROVIDER": "llm", "LOCAL_LLM_BASE_URL": "http://llm:1234/v1",
                                      "LOCAL_LLM_MODEL": "m"})


def test_llm_classifier_constrains_to_enums_and_repairs_once():
    bodies = []
    replies = iter([json.dumps({"moved": {"answer": "maybe", "confidence": 0.9}}),
                    json.dumps({"moved": {"answer": "yes", "confidence": 0.9},
                                "kind": {"answer": "momentum", "confidence": 0.8},
                                "size": {"answer": "a lot", "confidence": 0.5}})])

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=chat(next(replies)))

    model = from_settings(llm_settings(), httpx.MockTransport(handler))
    result = run(model.decide("STATE", QUESTIONS))
    schema = bodies[0]["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["moved", "kind", "size"]
    assert schema["properties"]["moved"]["properties"]["answer"]["enum"] == ["yes", "no"]
    assert schema["properties"]["size"]["properties"]["answer"]["enum"] == ["none", "some", "a lot"]
    assert "invalid" in bodies[1]["messages"][-1]["content"] and len(bodies) == 2
    assert result.answers["moved"].probability == 0.9
    assert result.answers["kind"].choice == "momentum" and result.answers["kind"].probabilities["result"] == pytest.approx(0.2)
    assert result.answers["size"].score == 2.0
    assert result.model == "local-model" and result.tokens["total_tokens"] == 30


def test_llm_classifier_fails_after_the_repair_turn():
    def handler(request):
        return httpx.Response(200, json=chat("not json"))

    model = from_settings(llm_settings(), httpx.MockTransport(handler))
    with pytest.raises(DecisionError, match="invalid reply twice"):
        run(model.decide("S", {"moved": QUESTIONS["moved"]}))


def test_fake_decisions_and_the_gate_priority():
    fake = FakeDecisions({"moved": 0.9, "size": 2})
    result = run(fake.decide("S", QUESTIONS))
    assert result.answers["moved"].probability == 0.9 and result.answers["size"].score == 2.0
    assert result.answers["kind"].choice == "momentum" and fake.calls[0][0] == "S"

    async def order():
        gate, seen = ModelGate(1), []

        async def call(kind):
            async with gate.slot("m", kind):
                seen.append(kind)
                await asyncio.sleep(0)

        async with gate.slot("m", "author"):
            tasks = [asyncio.create_task(call(k)) for k in ("author", "decision", "analysis", "summary")]
            await asyncio.sleep(0)
        await asyncio.gather(*tasks)
        return seen

    assert run(order()) == ["summary", "analysis", "decision", "author"]


def test_decision_one_waits_for_its_own_pacing_not_the_agents_model_gate():
    async def held(provider):
        gate = ModelGate(1)
        engine = SimpleNamespace(match_id="m", gate=gate,
                                 decisions=from_settings(settings(DECISION_PROVIDER=provider)))
        async with MatchOrchestrator.decision_slot(engine):
            return gate.running

    assert run(held("systemone")) == 0 and run(held("llm")) == 1


def test_settings_validate_provider_and_auth():
    with pytest.raises(ValueError):
        settings(DECISION_PROVIDER="other")
    with pytest.raises(ValueError):
        settings(DECISION_AUTH="cookie")
