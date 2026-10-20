"""Exercise the running Docker services over HTTP, GraphQL and WebSocket."""
import json
import os

import httpx
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from .replay import replay


def main():
    base = os.getenv("BACKEND_URL", "http://backend:8000")
    etl = os.getenv("FAKE_ETL_URL", "http://fake-etl:8000")
    narrative = os.getenv("FAKE_NARRATIVE_URL", "http://fake-narrative:8000")
    with httpx.Client(base_url=base, timeout=30) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        request("GET", "/ready")
        session = request("POST", "/sessions", json={"profile_id": "chelsea-analytical"})
        token = session["session_token"]
        path = f"/sessions/{token}"
        for pin in session["snapshot"]["pins"]:
            request("DELETE", path + "/pins/" + pin)
        request("PATCH", path + "/preferences", json={"team": "home", "fan_style": "analytical"})
        request("POST", path + "/pins", json={"calculation_id": "fixture-headers"})
        socket_url = base.replace("http://", "ws://").replace("https://", "wss://") + path + "/live"
        with connect(socket_url, open_timeout=10) as ws:
            assert json.loads(ws.recv(timeout=10))["type"] == "snapshot"
            replay(etl, narrative, interval=0)
            ws.send(json.dumps({"type": "ping"}))
            messages = []
            while True:
                message = json.loads(ws.recv(timeout=10))
                if message["type"] == "pong":
                    break
                messages.append(message)
            narratives = [m["data"] for m in messages if m["type"] == "narrative"]
            assert [n["id"] for n in narratives] == ["home-goal"], narratives
            state = request("GET", path)
            assert state["cards"] == [
                {"kind": "default", "id": "goals", "value": 1},
                {"kind": "default", "id": "shots", "value": 2},
                {"kind": "custom", "id": "fixture-headers", "value": 4},
            ], state["cards"]
            assert "var-1" in {moment["id"] for moment in state["key_moments"]}
            assert any(m.get("reason") == "match_event" for m in messages)

            replacement = request("POST", "/sessions", json={"profile_id": "chelsea-analytical"})
            assert replacement["snapshot"]["pins"] == ["fixture-headers"]
            try:
                ws.recv(timeout=10)
                raise AssertionError("Old session was not disconnected")
            except ConnectionClosed as exc:
                assert exc.rcvd.code == 4001
            assert client.get(path).status_code == 409

        # A corrected goal must also be correct through the independent ETL service.
        result = httpx.post(etl + "/graphql", json={"query":
            '{matchState(matchId:"synthetic-demo",team:"away")}'}, timeout=10).json()
        assert result["data"]["matchState"]["stats"]["goals"] == 0
        # Replaying event IDs cannot double count the pinned statistic.
        replay(etl, narrative, interval=0)
        restored = request("GET", "/sessions/" + replacement["session_token"])
        assert restored["cards"][-1]["value"] == 4
    print("PASS: fake services → GraphQL reads → backend → live cards/narratives; VAR, duplicate events and session takeover")


if __name__ == "__main__":
    main()
