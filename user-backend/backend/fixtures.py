"""Explicit upstream fixture adapter. Never used as a real narrative/model provider."""
import json
from pathlib import Path

from .domain import MatchEvent, Narrative, RuleError

STYLES = ("analytical", "simple", "casual", "experienced")
TEAMS = ("home", "away", "neutral")
SELECTIONS = {
    "analytical": ["possession", "shots", "goals", "cards"],
    "simple": ["goals", "cards", "shots", "possession"],
    "casual": ["goals", "shots", "cards", "possession"],
    "experienced": ["shots", "possession", "goals", "cards"],
}


class FixtureFeed:
    def __init__(self, match_id, slots):
        self.match_id, self.slots = match_id, slots
        self.events = {}
        data = json.loads((Path(__file__).parent.parent / "fixtures/match.json").read_text())
        for event in data["initial_events"]:
            self.accept_event(MatchEvent(match_id=match_id, **event))
        self.selections = {f"{team}:{style}": (0, list(SELECTIONS[style])) for team in TEAMS for style in STYLES}
        self.narratives = [Narrative(id=f"fixture-{team}-{style}", match_id=match_id,
                                    team=team, fan_style=style, minute=20,
                                    text="Synthetic development fixture: the match is evenly balanced.")
                           for team in TEAMS for style in STYLES]
        self.calculations = {
            "fixture-headers": {"label": "Headed touches (fixture)"},
            "fixture-corners": {"label": "Corners (fixture)"},
            "fixture-saves": {"label": "Saves (fixture)"},
            "fixture-tackles": {"label": "Tackles (fixture)"},
        }

    def history(self, bucket):
        return [n.model_dump() for n in self.narratives if n.bucket == bucket]

    def defaults(self, bucket):
        return list(self.selections[bucket][1])

    def accept(self, narrative):
        if narrative.match_id != self.match_id:
            raise RuleError("wrong_match", "Only the configured demo match is supported", 422)
        if narrative.stat_ids is not None and len(narrative.stat_ids) < self.slots:
            raise RuleError("invalid_selection", "Supply enough defaults to fill every slot", 422)
        # No parent-insight deduplication: that is the upstream engine's responsibility.
        self.narratives.append(narrative)
        if narrative.stat_ids is not None and narrative.minute >= self.selections[narrative.bucket][0]:
            self.selections[narrative.bucket] = (narrative.minute, list(narrative.stat_ids))

    def calculation(self, calculation_id):
        if calculation_id not in self.calculations:
            raise RuleError("calculation_not_found", "Unknown validated fixture calculation", 404)
        return self.calculations[calculation_id]

    def accept_event(self, event):
        if event.match_id != self.match_id:
            raise RuleError("wrong_match", "Only the configured demo match is supported", 422)
        if event.id in self.events:
            if self.events[event.id] != event:
                raise RuleError("event_conflict", "An event ID cannot be reused for different content", 422)
            return False
        if event.type == "goal_cancelled":
            original = self.events.get(event.related_event_id)
            if original is None or original.type != "goal" or original.team != event.team:
                raise RuleError("invalid_correction", "Cancellation must reference an existing goal for the same team", 422)
        self.events[event.id] = event
        return True

    def key_moments(self):
        return [event.model_dump() for event in sorted(self.events.values(), key=lambda e: e.sequence) if event.key_moment]

    def value(self, kind, key, team):
        if kind == "custom":
            self.calculation(key)
            if key == "fixture-headers":
                return sum(e.body_part == "head" for e in self.events.values())
            event_type = {"fixture-corners": "corner", "fixture-saves": "save", "fixture-tackles": "tackle"}[key]
            return sum(e.type == event_type for e in self.events.values())
        events = [e for e in self.events.values() if team == "neutral" or e.team == team]
        if key == "goals":
            cancelled = {e.related_event_id for e in events if e.type == "goal_cancelled"}
            return sum(e.type == "goal" and e.id not in cancelled for e in events)
        if key == "possession":
            # Deliberately supplied fixture state, not inferred from pass counts.
            return 50
        return sum(e.type == {"cards": "card", "shots": "shot"}[key] for e in events)

    def view(self, bucket, team):
        return {"defaults": self.defaults(bucket), "narratives": self.history(bucket),
                "key_moments": self.key_moments(),
                "values": {"default": {key: self.value("default", key, team) for key in SELECTIONS["simple"]},
                           "custom": {key: self.value("custom", key, team) for key in self.calculations}}}
