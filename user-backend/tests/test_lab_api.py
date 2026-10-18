"""Real PostgreSQL and HTTP tests for the removable filter lab."""
import json

import pytest
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


def test_clarification_round_trip_and_expiry_over_http(store):
    from backend.agents.models import Clarification, Goal, PlanOutcome

    class Planner:
        async def plan(self, prompt, context, history=None):
            if not history:
                return PlanOutcome(status="clarification", source="fixture", clarification=Clarification(
                    question="Which player?", options=["Mbappe"], missing_fields=["player"]))
            assert history[0]["content"] == "Track his headed shots"
            assert history[1]["content"] == "Which player?\nOptions:\n1. Mbappe"
            assert prompt == "Mbappe"
            goal = Goal(description="Mbappe headed attempts", player_ids=("mbappe",),
                        event_types=("shot", "goal"), body_part="head")
            return PlanOutcome(status="ready", source="fixture", goal=goal, rule=goal.target_rule(context["match_id"]))

    lab = make_lab(store)
    lab.planner = Planner()
    with TestClient(create_app(store, lab=lab)) as client:
        first = client.post("/lab/plan", json={"prompt": "Track his headed shots"}).json()
        assert first["status"] == "clarification" and first["rule"] is None
        reply = {"prompt": "Mbappe", "conversation_id": first["conversation_id"]}
        second = client.post("/lab/plan", json=reply).json()
        assert second["status"] == "ready"
        assert second["goal"]["player_ids"] == ["mbappe"]
        assert client.get("/lab/state").json()["calculations"] == []
        assert client.post("/lab/plan", json={**reply, "history": []}).status_code == 422
        client.post("/lab/reset")
        assert client.post("/lab/plan", json=reply).status_code == 409


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


def test_recording_download_and_received_event_inspection(store):
    lab = make_lab(store)
    with TestClient(create_app(store, lab=lab)) as client:
        metadata = client.get("/lab/scenario").json()["recording"]
        assert metadata["filename"] == "filter-lab.json"
        assert metadata["delivery_count"] == 35
        assert metadata["event_count"] == 30
        download = client.get("/lab/recording")
        assert download.content == lab.source.content
        assert "attachment" in download.headers["content-disposition"]
        assert client.get("/lab/events/0").status_code == 404
        client.portal.call(lab.advance)
        event = client.get("/lab/events/0").json()
        assert event["raw"] == lab.source.spec["events"][0]
        assert event["canonical"]["event_id"] == event["raw"]["eventId"]
        state = client.get("/lab/state").json()
        assert state["events"][0]["delivery_index"] == 0
        assert client.get("/lab/events/1").status_code == 404
        assert client.get("/lab/events/-1").status_code == 404
        client.post("/lab/reset")
        assert client.get("/lab/events/0").status_code == 404


def test_uploaded_recording_survives_restart_reset_and_default_restore(store):
    lab = make_lab(store)
    recording = lab.source.spec.copy()
    recording["events"] = recording["events"][:2]
    recording.pop("presets")
    content = json.dumps(recording).encode()
    with TestClient(create_app(store, lab=lab)) as client:
        initial = client.get("/lab/state").json()["run_id"]
        client.post("/lab/calculations", json={"rule": lab.source.spec["presets"][0]["rule"]})
        result = client.post("/lab/recording", content=content,
                             headers={"X-Recording-Filename": "short-match.json"})
        assert result.status_code == 200, result.text
        assert result.json()["state"]["run_id"] != initial
        assert result.json()["state"]["calculations"] == []
        assert result.json()["scenario"]["presets"] == []
        client.portal.call(lab.advance)
    with TestClient(create_app(store, lab=make_lab(store))) as client:
        assert client.get("/lab/state").json()["position"] == 1
        assert client.get("/lab/scenario").json()["recording"]["filename"] == "short-match.json"
        assert client.get("/lab/recording").content == content
        client.post("/lab/reset").raise_for_status()
        assert client.get("/lab/recording").content == content
        result = client.post("/lab/recording/default")
        assert result.status_code == 200
        assert result.json()["scenario"]["recording"]["filename"] == "filter-lab.json"
        assert result.json()["state"]["total"] == 35
    with TestClient(create_app(store, lab=make_lab(store))) as client:
        assert client.get("/lab/scenario").json()["recording"]["filename"] == "filter-lab.json"


@pytest.mark.parametrize("content,expected", [(b"not json", 422), (b"{}", 422), (b"x" * (2*1024*1024+1), 413)])
def test_invalid_recordings_preserve_current_run(store, content, expected):
    lab = make_lab(store)
    with TestClient(create_app(store, lab=lab)) as client:
        before = client.get("/lab/state").json()
        assert client.post("/lab/recording", content=content).status_code == expected
        assert client.get("/lab/state").json() == before


def test_recording_cannot_change_during_replay(store):
    lab = make_lab(store)
    with TestClient(create_app(store, lab=lab)) as client:
        client.post("/lab/replay/start", json={"interval_ms": 5000})
        response = client.post("/lab/recording", content=lab.source.content)
        assert response.status_code == 409
        assert client.post("/lab/recording/default").status_code == 409


def test_recording_persistence_failure_does_not_replace_current_source(store, monkeypatch):
    lab = make_lab(store)
    with TestClient(create_app(store, lab=lab)) as client:
        before = client.get("/lab/state").json()
        def fail(*args):
            raise OSError("Test database outage")
        monkeypatch.setattr(lab.repository, "replace_recording", fail)
        with pytest.raises(OSError):
            client.post("/lab/recording", content=lab.source.content,
                        headers={"X-Recording-Filename": "replacement.json"})
        assert client.get("/lab/state").json() == before
        assert lab.source.filename == "filter-lab.json"
