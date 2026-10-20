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

    def data_reference(self):
        reference = self.adapter.data_reference()
        if self.spec.get('provenance', {}).get('source') == 'Google Research Football instrumented native runtime':
            reference['contract_id'] = 'synthetic-grf-native-contacts-v1'
            reference['provenance'] = self.spec['provenance']['source'] + '; synthetic Opta-inspired adapter, not an official feed.'
            reference['events']['touch'] = (
                'Coalesced native ball contact, including intentional contacts and nonintentional deflections. '
                'A touch also accompanies passes and shooting attempts. Count touch records alone for captured '
                'contacts; adding pass, shot or goal records double-counts those actions.')
            reference['events']['goal'] += (
                ' In this GRF recording, a deflected scoring attempt can have an unknown scorer. '
                'Its original shot is merged into the goal, so the shooter is not recoverable from player_id.')
            reference['unavailable'] = [*reference['unavailable'],
                'Exhaustive player shooting totals are unavailable when a scoring attempt has an unknown player_id. '
                'Named-player counts cover attributed attempts only; do not present them as complete totals. '
                'Team shooting totals still count the scoring attempt once.']
        if capabilities := self.spec.get('capabilities'):
            reference['capabilities'] = dict(capabilities)
            reference['unavailable'] = [*reference['unavailable'],
                'Only event categories listed in capabilities.supported_event_types are captured in this recording. '
                'Missing categories are unavailable, not observed zero counts.']
            if capabilities.get('restart_events') == 'taken':
                reference['contract_id'] = 'synthetic-grf-native-contacts-v2'
                reference['events']['corner'] = (
                    'Corner actually taken by the recorded player/team. Its distribution or attempt is '
                    'a separate pass, shot or goal record; do not add restart and action counts.')
                reference['events']['foul'] = (
                    'Referee-whistled foul attributed to the offender. Offsides and unwhistled advantage '
                    'are excluded. A separate foul_won record belongs to the victim.')
                reference['events']['card'] = (
                    'Card decision attributed to the recipient. Outcome is yellow, second_yellow or red. '
                    'Second yellow is the dismissing decision, not an additional straight red.')
                reference['unavailable'] = [text.replace('Corner-taker identity, ', '')
                                            for text in reference['unavailable']]
                reference['guarantees'].append(
                    'Restart records count actual executions; accompanying pass/shot/goal records describe '
                    'the action. Raw restart and related-event qualifiers are not queryable canonical fields.')
            if capabilities.get('coordinates') == 'opta_0_100':
                reference['contract_id'] = 'synthetic-grf-opta-v3'
                # v3 derives goals from the attempt, so the scorer is the attempting player.
                reference['events']['goal'] = reference['events']['goal'].split(' In this GRF recording')[0]
            if (self.spec.get('provenance', {}).get('source') ==
                    'Google Research Football instrumented native runtime' and
                    'touch' in capabilities.get('supported_event_types', ())):
                # Native touch is the coalesced contact underlying action records.
                # Its tagged subset is countable even without exhaustive body-part coverage.
                reference['capabilities']['recorded_body_part_event_groups'] = [['touch']]
            if 'body_part_event_types' in capabilities:
                reference['guarantees'].append(
                    'Body-part filters require an explicit event category covered by body_part_event_types '
                    'unless body_parts is true. Recorded-only counts may use recorded_body_part_event_groups; '
                    'unclassified records are excluded, never inferred. Missing contact metadata remains unknown.')
        if not (self.spec.get('capabilities') or {}).get('coordinates'):
            reference['unavailable'] = [*reference['unavailable'],
                'This recording has no x/y coordinates, possession_id or extended qualifiers; those fields are null or empty.']
        return reference

    def history(self, position):
        """Only already-observed events, never future fixture data."""
        return self.events[:position]

    def playback_seconds(self, position):
        return self.video_times[position - 1] if self.timed and position else 0.0

    @property
    def playback_duration(self):
        return self.spec.get('playback', {}).get('duration_seconds', self.playback_seconds(len(self.events)))

    def replay_delay(self, position, fallback):
        if not self.timed or position >= len(self.events):
            return fallback
        return max(0.0, self.video_times[position] - self.playback_seconds(position))

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
