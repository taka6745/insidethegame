"""Routing sees intent only; numeric requests cannot reach the prose answer model."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from backend.adapters.llm import LocalJsonModel
from backend.agents.question import QuestionAgent
from backend.agents.question_intent import QuestionIntent, routing_context
from backend.services.question_answers import resolve_answer


def test_routing_context_excludes_values_and_keeps_immediate_stat_clarification():
    context = {
        "standard_stats": [{"id": "shots", "label": "Team shots", "definition": "Recorded shot attempts", "value": 987}],
        "compact": {"text": "Numerical recap 654"},
        "history": [
            {"user": "How many shots?", "reply": {"answer_kind": "statistic", "status": "answer",
                "standard_stat_id": "shots", "text": "987 shots", "goal": None}},
            {"user": "How many headers by the striker?", "reply": {"answer_kind": "statistic",
                "status": "clarification", "text": "Headed passes, shots or all recorded contacts?"}},
        ],
    }
    routed = routing_context(context)
    assert "987" not in json.dumps(routed)
    assert "654" not in json.dumps(routed)
    assert routed["dialogue"][-1]["intent"]["clarification"] == "Headed passes, shots or all recorded contacts?"
    assert routed["dialogue"][0]["intent"]["standard_stat"] == {"id": "shots", "label": "Team shots", "definition": "Recorded shot attempts"}


@pytest.mark.parametrize("decision", [
    {"route": "unknown"}, {"route": "clarification"},
    {"route": "statistic", "question": "999 shots"},
    {"route": "statistic", "value": 999},
])
def test_invalid_intent_fails_closed(decision):
    with pytest.raises(ValidationError):
        QuestionIntent.model_validate(decision)


def test_native_stat_route_calls_planner_without_exposing_events_or_answering_in_prose():
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        assert len(requests) == 1, "A statistic must not reach a prose-generating model"
        return httpx.Response(200, json={
            "id": "route", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"route":"statistic"}'}}],
        })

    class Tools:
        offers = []
        goal = None
        async def prepare_original(self):
            assert self.original_prompt == "How many headed shots?"
            self.offers = [{"id": "verified", "label": "Headed shots", "value": 3}]
            return {"status": "ready", "offer_id": "verified"}

    async def run():
        agent = QuestionAgent(LocalJsonModel("http://fake/v1", "test", transport=httpx.MockTransport(respond)))
        tools = Tools()
        draft = await agent.answer("How many headed shots?", {"compact": {"tail": ["DO NOT EXPOSE"]}}, tools)
        result = await resolve_answer(draft, tools)
        assert result.text == "Headed shots: 3."
        assert result.selected_offer_id == "verified"
    asyncio.run(run())
    assert "DO NOT EXPOSE" not in json.dumps(requests)
    assert not requests[0].get("tools")


def test_ambiguous_route_returns_question_without_calculation():
    class Router:
        async def route(self, prompt, context):
            return QuestionIntent(route="clarification", question="Headed passes, headed shots, or all headed contacts?")

    class Tools:
        offers = []
        goal = None
        async def prepare_original(self):
            raise AssertionError("Ambiguity must be resolved before calculation")

    async def run():
        tools = Tools()
        draft = await QuestionAgent(SimpleNamespace(), router=Router()).answer("How many headers by Bruno?", {}, tools)
        reply = await resolve_answer(draft, tools)
        assert reply.status == "clarification"
        assert "headed shots" in reply.text
        assert tools.offers == []
    asyncio.run(run())


def test_stat_followup_passes_original_conversation_to_existing_planner():
    from backend.agents.models import PlanOutcome
    from backend.services.question_tools import QuestionTools

    class Planner:
        async def plan(self, request, context, history):
            assert request == "What about in the second half?"
            assert history[-2]["content"] == "How many headed shots by the striker?"
            assert json.loads(history[-1]["content"])["goal"]["player_ids"] == ["striker"]
            return PlanOutcome(status="clarification", source="fixture", message="Which striker?")

    class Router:
        async def route(self, prompt, context):
            return QuestionIntent(route="statistic")

    payload = SimpleNamespace(snapshot=SimpleNamespace(match_id="m", clock_seconds=4000, period=2), players=[], teams=[])
    history = [
        {"user": "How many team shots?", "reply": {"text": "5 team shots"}},
        {"user": "How many headed shots by the striker?", "reply": {
            "goal": {"description": "Striker headed shots", "player_ids": ["striker"]}}},
    ]
    async def run():
        tools = QuestionTools(payload, None, None, Planner(), [], {}, history)
        agent = QuestionAgent(SimpleNamespace(), router=Router())
        draft = await agent.answer("What about in the second half?", {"history": history}, tools)
        result = await resolve_answer(draft, tools)
        assert result.status == "clarification" and result.text == "Which striker?"
    asyncio.run(run())


@pytest.mark.parametrize("route", ["football", "match"])
def test_rules_reference_is_included_only_for_general_football(route):
    class Router:
        async def route(self, prompt, context):
            return QuestionIntent(route=route)

    def respond(request):
        body = json.loads(request.content)
        context = json.loads(body["messages"][-1]["content"])
        assert ("football_reference" in context) == (route == "football")
        if route == "football":
            assert context["football_reference"], "The reference must be a real versioned document"
        decision = {"route": route, "text": "A short grounded explanation."}
        if route == "match":
            decision["evidence_ids"] = []
        return httpx.Response(200, json={
            "id": "answer", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"decision": decision})}}],
        })

    agent = QuestionAgent(LocalJsonModel("http://fake/v1", "test", transport=httpx.MockTransport(respond)), router=Router())
    reply = asyncio.run(agent.answer("Explain this", {}, SimpleNamespace()))
    assert reply.answer_kind == route


def test_provider_ignoring_native_schema_gets_same_prompt_contract_and_one_repair():
    class Model:
        calls = 0
        async def complete(self, instructions, payload, *, response_schema):
            self.calls += 1
            assert payload["routing_schema"] == response_schema
            assert set(response_schema["required"]) == {"route", "question"}
            assert "route" in payload["routing_schema"]["properties"]
            if self.calls == 1:
                return {"intent": "statistic"}  # Actual non-enforcing provider response.
            assert "validation_feedback" in payload
            return {"route": "statistic", "question": None}
    from backend.agents.question_intent import QuestionIntentRouter
    model = Model()
    result = asyncio.run(QuestionIntentRouter(model).route("How many shots?", {}))
    assert result.route == "statistic" and model.calls == 2


def test_router_rejects_invalid_contract_after_one_repair():
    class Model:
        calls = 0
        async def complete(self, *args, **kwargs):
            self.calls += 1
            return {"intent": "statistic"}
    from backend.agents.question_intent import QuestionIntentRouter
    model = Model()
    with pytest.raises(ValidationError):
        asyncio.run(QuestionIntentRouter(model).route("How many shots?", {}))
    assert model.calls == 2
