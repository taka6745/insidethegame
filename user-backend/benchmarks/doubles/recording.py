"""Test/benchmark reader for a synthetic recording file; the runtime never opens recordings."""
import hashlib
import json
from pathlib import Path

from benchmarks.doubles.events import OptaInspiredAdapter
from backend.adapters.match_reference import data_reference
from benchmarks.doubles.recording_model import Recording, MAX_RECORDING_BYTES


# Hand-authored fixtures without MA1 capabilities stand for a complete feed; the runtime never assumes it.
COMPLETE_CAPABILITIES = {'body_parts': True, 'shot_outcomes': True, 'coordinates': 'opta_0_100'}


class FixtureEventSource:
    MAX_BYTES = MAX_RECORDING_BYTES

    def __init__(self, path=None, adapter=None, *, content=None, filename=None):
        path = path or Path(__file__).parents[2] / "fixtures/filter-lab.json"
        content = Path(path).read_bytes() if content is None else content
        if len(content) > self.MAX_BYTES:
            raise ValueError("Recording must be no larger than 16 MiB")
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
        self.video_times = tuple(raw.get('videoSeconds') for raw in self.spec['events'])
        self.timed = all(value is not None for value in self.video_times)
        if self.timed and any(b < a for a, b in zip(self.video_times, self.video_times[1:])):
            raise ValueError('Recording video timestamps must be ordered')
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
            if key in revisions and not revisions[key].same_content(event):
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

    @property
    def capabilities(self):
        """MA1 capabilities (snake_case): the recording's, else the complete test contract."""
        return self.spec.get('capabilities') or COMPLETE_CAPABILITIES

    def data_reference(self):
        return data_reference(self.capabilities)

    def history(self, position):
        """Only already-observed events, never future fixture data."""
        return self.events[:position]

    def playback_seconds(self, position):
        return self.video_times[position - 1] if self.timed and position else 0.0

    @property
    def playback_duration(self):
        return self.spec.get('playback', {}).get('duration_seconds', self.playback_seconds(len(self.events)))

    def display(self, event):
        return {"id": event.event_id, "type": event.event_type,
                "player": self._players.get(event.player_id, event.player_id),
                "team": self._teams.get(event.team_id, event.team_id),
                "minute": event.match_time_seconds // 60,
                "match_time_seconds": event.match_time_seconds, "period": event.period,
                "body_part": event.body_part, "outcome": event.outcome,
                "revision": event.revision, "deleted": event.deleted,
                "synthetic": True}
