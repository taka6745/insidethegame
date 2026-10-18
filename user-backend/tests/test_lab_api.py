"""Real PostgreSQL and HTTP tests for the removable filter lab."""
from fastapi.testclient import TestClient

from backend.adapters.replay_source import FixtureEventSource
from backend.agents.fixtures import FixtureCodingAgent, FixtureGoalAgent
from backend.agents.workflow import RuleWorkflow
from backend.app import create_app
from backend.repositories.lab import PostgresLabRepository
from backend.services.lab import FilterLabService


def make_lab(store):
    return FilterLabService(FixtureEventSource(), PostgresLabRepository(store),
                            RuleWorkflow(FixtureGoalAgent(), FixtureCodingAgent(), source="fixture"))


def test_all_presets_replay_and_restore_from_postgres(store):
    lab = make_lab(store)
    with TestClient(create_app(store, lab=lab)) as client:
        scenario = client.get("/lab/scenario").json()
        assert scenario["synthetic"] is True
        assert "events" not in scenario
        assert all("expected_final" not in row for row in scenario["presets"])
        expected = {}
        for preset in lab.source.spec["presets"]:
            response = client.post("/lab/calculations", json={"rule": preset["rule"], "label": preset["label"]})
            assert response.status_code == 201, response.text
            result = response.json()
            assert result["value"] == 0
            expected[result["id"]] = preset["expected_final"]
        for _ in lab.source.events:
            client.portal.call(lab.advance)
        state = client.get("/lab/state").json()
        assert state["status"] == "finished"
        assert state["position"] == len(lab.source.events)
        assert {row["id"]: row["value"] for row in state["calculations"]} == expected
        assert client.post("/lab/replay/start", json={}).status_code == 409

    restored = make_lab(store)
    with TestClient(create_app(store, lab=restored)) as client:
        snapshot = client.get("/lab/state").json()
        assert snapshot["position"] == state["position"]
        assert sorted(snapshot["calculations"], key=lambda r: r["id"]) == sorted(state["calculations"], key=lambda r: r["id"])
        old_run = snapshot["run_id"]
        reset = client.post("/lab/reset").json()
        assert reset["run_id"] != old_run
        assert reset["position"] == 0
        assert reset["calculations"] == []
        assert reset["status"] == "ready"
        assert client.get("/profiles").status_code == 200


def test_plan_add_deduplicate_and_late_registration(store):
    lab = make_lab(store)
    with TestClient(create_app(store, lab=lab)) as client:
        plan = client.post("/lab/plan", json={"prompt": "Track total headers in this game by Mbappe"}).json()
        assert plan["status"] == "ready"
        assert plan["source"] == "fixture"
        for _ in range(12):
            client.portal.call(lab.advance)
        request = {"rule": plan["rule"], "label": "Mbappe headers"}
        first = client.post("/lab/calculations", json=request).json()
        duplicate = client.post("/lab/calculations", json=request).json()
        assert duplicate == first
        state = client.get("/lab/state").json()
        assert len(state["calculations"]) == 1
        assert len(state["events"]) == 12
        # Only the already-observed prefix contributes when a rule is registered.
        from backend.services.filter_engine import FilterEngine
        from backend.models.rules import Rule
        expected = FilterEngine().register(Rule.model_validate(plan["rule"]), lab.source.history(12))
        assert first["value"] == expected.value
        while client.portal.call(lab.advance):
            pass
        final = client.get("/lab/state").json()["calculations"][0]
        assert final["value"] == lab.source.spec["presets"][0]["expected_final"]


def test_invalid_requests_and_running_restart(store):
    lab = make_lab(store)
    with TestClient(create_app(store, lab=lab)) as client:
        rule = lab.source.spec["presets"][0]["rule"].copy()
        rule["match_id"] = "different-match"
        assert client.post("/lab/calculations", json={"rule": rule}).status_code == 422
        assert client.post("/lab/calculations", json={"rule": {"python": "arbitrary code"}}).status_code == 422
        assert client.post("/lab/plan", json={"prompt": ""}).status_code == 422
        assert client.post("/lab/replay/start", json={"interval_ms": 5000}).status_code == 200
        assert client.post("/lab/replay/start", json={}).status_code == 409
    # A process restart preserves the run but waits for an explicit Start.
    with TestClient(create_app(store, lab=make_lab(store))) as client:
        assert client.get("/lab/state").json()["status"] == "ready"
