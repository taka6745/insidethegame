"""Check the frontend proxy, persisted rules and a complete forward replay."""
import time

import httpx

from backend.adapters.replay_source import FixtureEventSource


def main():
    with httpx.Client(base_url="http://frontend/api", timeout=15) as client:
        client.post("/reset").raise_for_status()
        scenario = client.get("/scenario")
        scenario.raise_for_status()
        assert scenario.json()["synthetic"] is True
        expected = {}
        for preset in FixtureEventSource().spec["presets"]:
            response = client.post("/calculations", json={"rule": preset["rule"], "label": preset["label"]})
            response.raise_for_status()
            expected[response.json()["id"]] = preset["expected_final"]
        client.post("/replay/start", json={"interval_ms": 50}).raise_for_status()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = client.get("/state")
            response.raise_for_status()
            state = response.json()
            assert state["status"] != "error", state["error"]
            if state["status"] == "finished":
                break
            time.sleep(0.1)
        else:
            raise AssertionError("Filter lab replay did not finish")
        assert {row["id"]: row["value"] for row in state["calculations"]} == expected
        assert state["position"] == state["total"] == 35
        client.post("/reset").raise_for_status()
    print("Filter lab: frontend proxy, 26 presets, 35 deliveries and reset verified")


if __name__ == "__main__":
    main()
