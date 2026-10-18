import asyncio
import json
from pathlib import Path

import httpx
import pytest

from backend.adapters.llm import LocalJsonModel, ModelError
from backend.agents.compiler import RuleCodingAgent
from backend.agents.fixtures import FixtureGoalAgent, FixtureCodingAgent
from backend.agents.models import Goal
from backend.agents.orchestrator import GoalAgent
from backend.agents.workflow import RuleWorkflow, workflow_from_env


CONTEXT = {"match_id": "match-1", "players": [{"id": "mbappe", "name": "Mbappé"}],
           "teams": [{"id": "chelsea", "name": "Chelsea"}], "standard_stats": []}
GOAL = Goal(description="Chelsea corners after minute 60", event_types=("corner",),
            team_ids=("chelsea",), after_seconds=3600)


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def complete(self, system, payload):
        self.calls.append(payload)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def run(responses, context=CONTEXT):
    model = ScriptedModel(responses)
    result = asyncio.run(RuleWorkflow(GoalAgent(model), RuleCodingAgent(model)).plan("Track corners", context))
    return result, model


def goal_decision(goal=GOAL):
    return {"status": "custom", "goal": goal.model_dump(mode="json")}


def test_goal_compiler_validated_rule():
    result, model = run([goal_decision(), GOAL.target_rule("match-1").model_dump(mode="json")])
    assert result.status == "ready" and result.attempts == 1
    assert result.rule.calculation_id == GOAL.target_rule("match-1").calculation_id
    assert model.calls[1]["goal"]["after_seconds"] == 3600


def test_semantically_wrong_valid_rule_is_repaired():
    wrong = Goal(description="All corners", event_types=("corner",)).target_rule("match-1")
    result, model = run([goal_decision(), wrong.model_dump(mode="json"), GOAL.target_rule("match-1").model_dump(mode="json")])
    assert result.status == "ready" and result.attempts == 2
    assert "preserve" in model.calls[2]["validation_feedback"]


def test_initial_plus_three_repairs_then_clear_failure():
    result, model = run([goal_decision(), {}, {}, {}, {}])
    assert result.status == "failed" and result.attempts == 4 and result.rule is None
    assert len(model.calls) == 5


@pytest.mark.parametrize("decision", [
    {"status": "clarification", "message": "Headed touches or headed shots?"},
    {"status": "unsupported", "message": "Defensive pressure is interpretive."},
])
def test_no_coding_call_for_non_custom_decision(decision):
    result, model = run([decision])
    assert result.status == decision["status"] and result.attempts == 0
    assert len(model.calls) == 1


def test_reuse_only_catalogued_stat():
    context = {**CONTEXT, "standard_stats": [{"id": "goals", "description": "Match goals"}]}
    result, model = run([{"status": "reuse", "standard_stat_id": "goals"}], context)
    assert result.status == "reuse" and len(model.calls) == 1
    result, _ = run([{"status": "reuse", "standard_stat_id": "invented"}] * 2, context)
    assert result.status == "failed"


def test_unknown_entities_need_clarification():
    unknown = Goal(description="Unknown player", player_ids=("not-in-match",))
    result, model = run([goal_decision(unknown)])
    assert result.status == "clarification" and len(model.calls) == 1


def test_network_failure_does_not_silently_use_fixture():
    result, _ = run([ModelError("model unavailable")] * 2)
    assert result.status == "failed" and result.source == "local"


def test_goal_retries_transient_failure_once():
    result, model = run([ModelError("temporary error"), goal_decision(), GOAL.target_rule("match-1").model_dump(mode="json")])
    assert result.status == "ready" and len(model.calls) == 3


def test_goal_retries_invalid_schema_once():
    result, model = run([{"wrong": "schema"}, goal_decision(), GOAL.target_rule("match-1").model_dump(mode="json")])
    assert result.status == "ready" and len(model.calls) == 3


def test_goal_does_not_retry_authentication_error():
    result, model = run([ModelError("authentication failure", reason="http_401", retryable=False)])
    assert result.status == "failed" and len(model.calls) == 1


def test_whole_workflow_deadline_cancels_slow_model():
    class SlowModel:
        async def complete(self, system, payload):
            await asyncio.sleep(10)
    workflow = RuleWorkflow(GoalAgent(SlowModel()), RuleCodingAgent(SlowModel()), timeout_seconds=0.01)
    result = asyncio.run(workflow.plan("Track corners", CONTEXT))
    assert result.status == "failed" and "timed out" in result.message


def test_fixture_requests_are_explicit_and_boundaries_preserved():
    workflow = RuleWorkflow(FixtureGoalAgent(), FixtureCodingAgent(), source="fixture")
    for prompt, field, op, value in [
        ("Track Chelsea's corners after the 60th minute", "match_time_seconds", "gt", 3600),
        ("Track headers since minute 20", "match_time_seconds", "gte", 1200),
        ("Track second-half corners", "period", "eq", 2),
        ("Track total headers in this game by Mbappé", "body_part", "eq", "head"),
    ]:
        result = asyncio.run(workflow.plan(prompt, CONTEXT))
        assert result.status == "ready" and result.source == "fixture"
        assert any(p.field == field and p.op == op and p.value == value for p in result.rule.predicates)
    result = asyncio.run(workflow.plan("Track Chelsea corners only if they are losing", CONTEXT))
    assert result.status == "unsupported"  # Never silently drop the extra condition.


def test_goal_rejects_unsupported_categories_and_invalid_windows():
    for fields in ({"event_types": ["header"]}, {"after_seconds": 60, "from_seconds": 60},
                   {"after_seconds": 120, "before_seconds": 60}):
        with pytest.raises(ValueError):
            Goal(description="Bad goal", **fields)


def test_every_fixture_preset_can_be_planned_without_a_model():
    scenario = json.loads((Path(__file__).resolve().parents[1] / "fixtures/filter-lab.json").read_text())
    workflow = RuleWorkflow(FixtureGoalAgent(), FixtureCodingAgent(), source="fixture")
    from backend.models.rules import Rule
    for preset in scenario["presets"]:
        result = asyncio.run(workflow.plan(preset["label"], scenario))
        assert result.status == "ready", (preset["id"], result.message)
        assert result.rule.calculation_id == Rule.model_validate(preset["rule"]).calculation_id


def completion(content, finish_reason="stop"):
    return {"id": "test-completion", "object": "chat.completion", "created": 1,
            "model": "development-model", "choices": [{"index": 0, "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": content}}]}


def test_local_adapter_request_and_single_json_object():
    def respond(request):
        payload = json.loads(request.content)
        assert payload["model"] == "development-model"
        assert request.headers["authorization"] == "Bearer test-secret"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json=completion('```json\n{"ok": true}\n```'))
    model = LocalJsonModel("http://local.invalid/v1", "development-model", "test-secret", transport=httpx.MockTransport(respond))
    assert asyncio.run(model.complete("JSON only", {"request": "synthetic"})) == {"ok": True}


@pytest.mark.parametrize("status,body", [(401, {"secret": "provider-detail"}), (200, {"choices": []}),
                                        (200, {"choices": [{"message": {"content": "not JSON"}}]})])
def test_local_adapter_redacts_failed_responses(status, body):
    model = LocalJsonModel("http://private.invalid/v1", "model", "secret", transport=httpx.MockTransport(
        lambda _: httpx.Response(status, json=body)))
    with pytest.raises(ModelError) as failure:
        asyncio.run(model.complete("", {}))
    assert "secret" not in str(failure.value) and "private" not in str(failure.value)


def test_local_adapter_classifies_truncated_output():
    model = LocalJsonModel("http://local.invalid/v1", "model", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=completion("", "length"))))
    with pytest.raises(ModelError) as failure:
        asyncio.run(model.complete("", {}))
    assert failure.value.reason == "truncated_output" and failure.value.retryable


def test_auth_failure_is_not_retryable():
    model = LocalJsonModel("http://local.invalid/v1", "model", transport=httpx.MockTransport(
        lambda _: httpx.Response(401, json={"error": "private detail"})))
    with pytest.raises(ModelError) as failure:
        asyncio.run(model.complete("", {}))
    assert failure.value.reason == "http_401" and not failure.value.retryable


def test_factory_requires_explicit_valid_mode(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_MODE", "fixture")
    assert workflow_from_env().source == "fixture"
    monkeypatch.setenv("LOCAL_LLM_MODE", "local")
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    with pytest.raises(ModelError):
        workflow_from_env()
    monkeypatch.setenv("LOCAL_LLM_MODE", "typo")
    with pytest.raises(ValueError):
        workflow_from_env()


def test_framework_agents_and_workflow_repair_end_to_end(monkeypatch):
    from agent_framework import Agent, Workflow
    runs, requests = [], []
    original_run = Agent.run

    def observe_run(self, *args, **kwargs):
        runs.append(self.name)
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(Agent, "run", observe_run)

    def respond(request):
        body = json.loads(request.content)
        payload = json.loads(body["messages"][-1]["content"])
        requests.append(payload)
        if "decision_schema" in payload:
            response = goal_decision()
        elif payload["validation_feedback"] is None:
            response = Goal(description="Wrong: all corners", event_types=("corner",)).target_rule("match-1").model_dump(mode="json")
        else:
            response = GOAL.target_rule("match-1").model_dump(mode="json")
        return httpx.Response(200, json=completion(json.dumps(response)))

    transport = httpx.MockTransport(respond)
    workflow = RuleWorkflow(
        GoalAgent(LocalJsonModel("http://local.invalid/v1", "development-model", transport=transport, name="question_goal")),
        RuleCodingAgent(LocalJsonModel("http://local.invalid/v1", "development-model", transport=transport, name="rule_coder")))
    assert isinstance(workflow.build(), Workflow)
    result = asyncio.run(workflow.plan("Track Chelsea corners after 60 minutes", CONTEXT))
    assert result.status == "ready" and result.attempts == 2
    assert result.rule.calculation_id == GOAL.target_rule("match-1").calculation_id
    assert runs == ["question_goal", "rule_coder", "rule_coder"]
    assert "preserve" in requests[-1]["validation_feedback"]


def test_framework_has_no_hidden_transport_retries():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "private response"})

    model = LocalJsonModel("http://local.invalid/v1", "model", transport=httpx.MockTransport(respond))
    with pytest.raises(ModelError) as failure:
        asyncio.run(model.complete("JSON only", {}))
    assert len(calls) == 1
    assert failure.value.reason == "http_429" and failure.value.retryable


def test_framework_transport_error_is_redacted():
    def respond(request):
        raise httpx.ConnectError("private endpoint and credential", request=request)
    model = LocalJsonModel("http://local.invalid/v1", "model", transport=httpx.MockTransport(respond))
    with pytest.raises(ModelError) as failure:
        asyncio.run(model.complete("JSON only", {}))
    assert failure.value.reason == "transport_error"
    assert "private" not in str(failure.value)


def test_coding_auth_failure_stops_without_three_repairs():
    result, model = run([goal_decision(), ModelError("Request rejected", reason="http_401", retryable=False)])
    assert result.status == "failed" and result.attempts == 1
    assert len(model.calls) == 2


def test_concurrent_workflow_requests_do_not_share_match_context():
    class ContextGoalAgent:
        async def define(self, prompt, context):
            await asyncio.sleep(0)
            from backend.agents.models import GoalDecision
            return GoalDecision(status="custom", goal=Goal(description=prompt, player_ids=(context["players"][0]["id"],)))

    class ContextCoder:
        async def generate(self, goal, match_id, feedback):
            await asyncio.sleep(0)
            return goal.target_rule(match_id)

    workflow = RuleWorkflow(ContextGoalAgent(), ContextCoder())

    async def parallel():
        return await asyncio.gather(*(workflow.plan("Track player events", {
            "match_id": f"match-{i}", "players": [{"id": f"player-{i}"}]}) for i in range(5)))
    results = asyncio.run(parallel())
    for i, result in enumerate(results):
        assert result.status == "ready" and result.rule.match_id == f"match-{i}"
        assert result.goal.player_ids == (f"player-{i}",)
