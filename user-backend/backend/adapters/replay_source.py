"""Replaceable forward-only fixture source; provider keys stay in the event adapter."""
import hashlib
import json
from pathlib import Path

from backend.adapters.events import OptaInspiredAdapter


class FixtureEventSource:
    def __init__(self, path=None, adapter=None):
        path = path or Path(__file__).parents[2] / "fixtures/filter-lab.json"
        content = Path(path).read_bytes()
        self.fingerprint = hashlib.sha256(content).hexdigest()
        self.spec = json.loads(content)
        self.adapter = adapter or OptaInspiredAdapter()
        self.events = tuple(self.adapter.adapt(raw) for raw in self.spec["events"])
        self.match_id = self.spec["match_id"]
        if any(event.match_id != self.match_id for event in self.events):
            raise ValueError("Fixture events must belong to the scenario match")
        self._players = {p["id"]: p["name"] for p in self.spec["players"]}
        self._teams = {t["id"]: t["name"] for t in self.spec["teams"]}

    def describe(self):
        return {"synthetic": True, "match_id": self.match_id, "event_count": len(self.events),
                "players": self.spec["players"], "teams": self.spec["teams"],
                "presets": [{k: preset[k] for k in ("id", "label", "rule")} for preset in self.spec["presets"]]}

    def history(self, position):
        """Only already-observed events, never future fixture data."""
        return self.events[:position]

    def next_event(self, position):
        return self.events[position] if position < len(self.events) else None

    def display(self, event):
        return {"id": event.event_id, "type": event.event_type,
                "player": self._players.get(event.player_id, event.player_id),
                "team": self._teams.get(event.team_id, event.team_id),
                "minute": event.match_time_seconds // 60,
                "match_time_seconds": event.match_time_seconds, "period": event.period,
                "body_part": event.body_part, "outcome": event.outcome,
                "revision": event.revision, "deleted": event.deleted,
                "synthetic": True}
