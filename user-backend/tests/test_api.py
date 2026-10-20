from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import create_app


def ids(snapshot):
    return [card["id"] for card in snapshot["cards"]]


def narrative(**changes):
    return dict(id="n1", match_id="synthetic-demo", team="home", fan_style="analytical",
                minute=30, text="Synthetic goal fixture", **changes)


def test_join_loads_bucket_backlog_and_key_moments(client, token):
    state = client.get(f"/sessions/{token}").json()
    assert state["synthetic"] and state["bucket"] == "home:analytical"
    assert ids(state) == ["possession", "shots", "goals"]
    assert len(state["narratives"]) == 1
    assert state["key_moments"][0]["id"] == "shot-1"


def test_pin_replace_unpin_and_selection_change(client, token):
    path = f"/sessions/{token}"
    pinned = client.post(path + "/pins", json={"calculation_id": "fixture-headers"}).json()
    assert ids(pinned) == ["possession", "shots", "fixture-headers"]
    assert pinned["cards"][-1]["value"] == 2
    assert client.post("/dev/narratives", json=narrative(stat_ids=["goals", "cards", "shots", "possession"])).status_code == 202
    assert ids(client.get(path).json()) == ["goals", "cards", "fixture-headers"]
    assert ids(client.delete(path + "/pins/fixture-headers").json()) == ["goals", "cards", "shots"]


def test_full_cards_require_explicit_replacement(client, token):
    path = f"/sessions/{token}/pins"
    for key in ("fixture-headers", "fixture-corners", "fixture-saves"):
        assert client.post(path, json={"calculation_id": key}).status_code == 200
    response = client.post(path, json={"calculation_id": "fixture-tackles"})
    assert response.status_code == 409 and response.json()["code"] == "choose_pin_to_replace"
    replaced = client.post(path, json={"calculation_id": "fixture-tackles", "replace": "fixture-corners"}).json()
    assert ids(replaced) == ["fixture-headers", "fixture-tackles", "fixture-saves"]


def test_repeat_pin_and_concurrent_pins_preserve_slots(client, token):
    def add(key):
        return client.post(f"/sessions/{token}/pins", json={"calculation_id": key})
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(add, ["fixture-headers", "fixture-corners", "fixture-headers"]))
    assert all(response.status_code == 200 for response in responses)
    state = client.get(f"/sessions/{token}").json()
    assert len(state["cards"]) == 3 and set(state["pins"]) == {"fixture-headers", "fixture-corners"}


def test_takeover_revokes_http_and_closes_socket(client, token):
    with client.websocket_connect(f"/sessions/{token}/live") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        new = client.post("/sessions", json={"profile_id": "chelsea-analytical"}).json()["session_token"]
        assert new != token
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4001
    assert client.get(f"/sessions/{token}").status_code == 409
    assert client.post(f"/sessions/{token}/pins", json={"calculation_id": "fixture-saves"}).status_code == 409


def test_one_socket_per_session(client, token):
    with client.websocket_connect(f"/sessions/{token}/live") as first:
        first.receive_json()
        with client.websocket_connect(f"/sessions/{token}/live") as second:
            second.receive_json()
            with pytest.raises(WebSocketDisconnect):
                first.receive_json()
            second.send_json({"type": "ping"})
            assert second.receive_json() == {"type": "pong"}


def test_repeated_disconnects_clean_up_socket_tasks(client, token):
    for _ in range(20):
        with client.websocket_connect(f"/sessions/{token}/live") as ws:
            assert ws.receive_json()["type"] == "snapshot"
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}


def test_pins_preferences_survive_new_session_and_new_app(client, token, store):
    client.post(f"/sessions/{token}/pins", json={"calculation_id": "fixture-headers"})
    client.patch(f"/sessions/{token}/preferences", json={"team": "away", "fan_style": "simple"})
    with TestClient(create_app(store)) as restarted:
        new = restarted.post("/sessions", json={"profile_id": "chelsea-analytical"}).json()
        assert new["snapshot"]["bucket"] == "away:simple"
        assert new["snapshot"]["pins"] == ["fixture-headers"]


def test_only_matching_bucket_receives_narrative(client, token):
    away = client.post("/sessions", json={"profile_id": "united-casual"}).json()["session_token"]
    with client.websocket_connect(f"/sessions/{token}/live") as home_ws, client.websocket_connect(f"/sessions/{away}/live") as away_ws:
        home_ws.receive_json(); away_ws.receive_json()
        assert client.post("/dev/narratives", json=narrative()).status_code == 202
        assert home_ws.receive_json()["type"] == "narrative"
        assert home_ws.receive_json()["reason"] == "narrative_received"
        away_ws.send_json({"type": "ping"})
        assert away_ws.receive_json() == {"type": "pong"}
    assert all(n["id"] != "n1" for n in client.get(f"/sessions/{away}").json()["narratives"])


def test_events_update_custom_pin_without_double_counting(client, token):
    client.post(f"/sessions/{token}/pins", json={"calculation_id": "fixture-headers"})
    event = {"id": "header-live", "match_id": "synthetic-demo", "sequence": 8, "minute": 21,
             "team": "away", "type": "shot", "body_part": "head"}
    with client.websocket_connect(f"/sessions/{token}/live") as ws:
        ws.receive_json()
        assert client.post("/dev/events", json=event).status_code == 202
        assert ws.receive_json()["data"]["cards"][-1]["value"] == 3
        assert client.post("/dev/events", json=event).json()["duplicate"]
    assert client.get(f"/sessions/{token}").json()["cards"][-1]["value"] == 3


@pytest.mark.parametrize("selection", [["goals", "unknown", "shots"], ["goals", "goals", "cards"], ["goals"]])
def test_invalid_stat_instruction_does_not_change_state(client, token, selection):
    before = client.get(f"/sessions/{token}").json()
    assert client.post("/dev/narratives", json=narrative(stat_ids=selection)).status_code == 422
    assert client.get(f"/sessions/{token}").json() == before


def test_stale_selection_does_not_rewind_live_cards(client, token):
    newest = narrative(stat_ids=["cards", "goals", "shots", "possession"])
    client.post("/dev/narratives", json=newest)
    older = {**newest, "id": "older", "minute": 29, "stat_ids": ["shots", "cards", "goals", "possession"]}
    client.post("/dev/narratives", json=older)
    assert ids(client.get(f"/sessions/{token}").json()) == ["cards", "goals", "shots"]


def test_invalid_inputs_and_disabled_injection(client, token, store):
    assert client.post("/sessions", json={"profile_id": "missing"}).status_code == 404
    assert client.get("/sessions/not-a-token").status_code == 422
    assert client.patch(f"/sessions/{token}/preferences", json={"team": "other", "fan_style": "simple"}).status_code == 422
    assert client.post(f"/sessions/{token}/pins", json={"calculation_id": "unvalidated"}).status_code == 404
    with TestClient(create_app(store)) as safe:
        assert safe.post("/dev/narratives", json=narrative()).status_code == 404
        assert safe.post("/dev/events", json={}).status_code == 404


@pytest.mark.parametrize("team", ["home", "away", "neutral"])
@pytest.mark.parametrize("style", ["analytical", "simple", "casual", "experienced"])
def test_all_twelve_buckets_have_matching_backlog_and_cards(client, token, team, style):
    response = client.patch(f"/sessions/{token}/preferences", json={"team": team, "fan_style": style})
    assert response.status_code == 200
    state = response.json()
    assert state["bucket"] == f"{team}:{style}"
    assert len(state["cards"]) == 3
    assert state["narratives"]
    assert all(n["team"] == team and n["fan_style"] == style for n in state["narratives"])
