"""Replaceable forward-only fixture source; provider keys stay in the event adapter."""
import hashlib
import json
from pathlib import Path

from backend.adapters.events import OptaInspiredAdapter
from backend.models.recording import Recording, MAX_RECORDING_BYTES


class FixtureEventSource:
    MAX_BYTES = MAX_RECORDING_BYTES

    def __init__(self, path=None, adapter=None, *, content=None, filename=None):
        path = path or Path(__file__).parents[2] / "fixtures/filter-lab.json"
        content = Path(path).read_bytes() if content is None else content
        if len(content) > self.MAX_BYTES:
            raise ValueError("Recording must be no larger than 2 MiB")
        self.content = content
        self.filename = Path((filename or Path(path).name).replace("\\", "/")).name[:160]
        if not self.filename or any(ord(char) < 32 for char in self.filename):
            raise ValueError("Recording filename is invalid")
        self.fingerprint = hashlib.sha256(content).hexdigest()
        self.spec = json.loads(content.decode("utf-8"))
        Recording.model_validate(self.spec)
        self.spec.setdefault("presets", [])
        self.adapter = adapter or OptaInspiredAdapter()
        self.events = tuple(self.adapter.adapt(raw) for raw in self.spec["events"])
        self.match_id = self.spec["match_id"]
        if any(event.match_id != self.match_id for event in self.events):
            raise ValueError("Fixture events must belong to the scenario match")
        self._players = {p["id"]: p["name"] for p in self.spec["players"]}
        self._teams = {t["id"]: t["name"] for t in self.spec["teams"]}
        if any((e.player_id is not None and e.player_id not in self._players) or
               (e.team_id is not None and e.team_id not in self._teams) for e in self.events):
            raise ValueError("Events must reference listed players and teams")
        revisions = {}
        for event in self.events:
            key = event.event_id, event.revision
            if key in revisions and revisions[key] != event:
                raise ValueError("The same event revision has conflicting contents")
            revisions[key] = event

    def with_recording(self, content, filename):
        return type(self)(adapter=self.adapter, content=content, filename=filename)

    def describe(self):
        return {"synthetic": True, "match_id": self.match_id, "event_count": len(self.events),
                "recording": {"filename": self.filename,
                              "title": " vs ".join(self._teams.values()),
                              "format": "Opta-inspired JSON", "synthetic": True,
                              "delivery_count": len(self.events),
                              "event_count": len({e.event_id for e in self.events})},
                "players": self.spec["players"], "teams": self.spec["teams"],
                "presets": [{k: preset[k] for k in ("id", "label", "rule")} for preset in self.spec["presets"]]}

    def history(self, position):
        """Only already-observed events, never future fixture data."""
        return self.events[:position]

    def next_event(self, position):
        return self.events[position] if position < len(self.events) else None

    def inspect(self, delivery_index):
        return {"delivery_index": delivery_index, "raw": self.spec["events"][delivery_index],
                "canonical": self.events[delivery_index].model_dump(mode="json")}

    def display_delivery(self, index):
        return {**self.display(self.events[index]), "delivery_index": index,
                "key_moment": self.spec["events"][index].get("keyMoment")}

    def display(self, event):
        return {"id": event.event_id, "type": event.event_type,
                "player": self._players.get(event.player_id, event.player_id),
                "team": self._teams.get(event.team_id, event.team_id),
                "minute": event.match_time_seconds // 60,
                "match_time_seconds": event.match_time_seconds, "period": event.period,
                "body_part": event.body_part, "outcome": event.outcome,
                "revision": event.revision, "deleted": event.deleted,
                "synthetic": True}
