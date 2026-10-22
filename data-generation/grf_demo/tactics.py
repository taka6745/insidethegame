"""Scripted team tactics: a policy layer that steers the built-in AIs through engine knobs.

Each fixture's script in tactics.json gives every team a base style and a list of phases.
A phase applies in a broadcast-minute window [from, to) and optionally only in a game state
(`when`: leading, trailing or level, from that team's view). `set` steers the phase's team and
`opponent` the other team. Later phases override earlier ones; `ramp` moves linearly from the
value before the phase to the target across the window.
Knobs and their ranges are documented in prepare_tactics.py.
"""

import json
from pathlib import Path

from .prepare_tactics import DEFAULTS, KNOBS

SCRIPTS = Path(__file__).with_name("tactics.json")


def load(fixture_name, path=SCRIPTS):
    script = json.loads(path.read_text())[fixture_name]
    validate(script)
    return script


def validate(script):
    for team, style in script["styles"].items():
        unknown = set(style) - set(KNOBS)
        if unknown:
            raise ValueError(f"Unknown tactic knobs for {team}: {sorted(unknown)}")
    for phase in script["phases"]:
        if set(phase["set"]) - set(KNOBS) or set(phase.get("opponent", {})) - set(KNOBS) \
                or phase["team"] not in script["styles"]:
            raise ValueError(f"Invalid phase {phase['label']!r}")
        if phase.get("when") not in (None, "leading", "trailing", "level"):
            raise ValueError(f"Invalid game state in {phase['label']!r}")


def state(score, team):
    diff = score[team] - score[1 - team]
    return "leading" if diff > 0 else "trailing" if diff < 0 else "level"


def evaluate(script, team_ids, minute, score):
    """Knob values and active phase labels per team index at a broadcast minute and score."""
    result = []
    for index, team_id in enumerate(team_ids):
        values = {**DEFAULTS, **script["styles"][team_id]}
        labels = []
        for phase in script["phases"]:
            start, end = phase["from"], phase.get("to", 1e9)
            own = phase["team"] == team_id
            targets = phase["set"] if own else phase.get("opponent")
            if not targets or not start <= minute < end:
                continue
            if phase.get("when") and phase["when"] != state(score, index if own else 1 - index):
                continue
            share = (minute - start) / (end - start) if phase.get("ramp") else 1.0
            for knob, target in targets.items():
                values[knob] += (target - values[knob]) * share
            labels.append(phase["label"])
        result.append(({k: round(v, 3) for k, v in values.items()}, labels))
    return result


class Policy:
    """Applies a script to a running native engine once per second of video."""

    def __init__(self, script, team_ids, set_tactic):
        self.script, self.team_ids, self.set_tactic = script, team_ids, set_tactic
        self.current = [None, None]
        self.changes = []

    def apply(self, video, minute, score):
        for index, (values, labels) in enumerate(evaluate(self.script, self.team_ids, minute, score)):
            previous = self.current[index]
            for knob, value in values.items():
                if previous is None or previous[0][knob] != value:
                    if not self.set_tactic(index, knob, float(value)):
                        raise ValueError(f"Engine lacks tactic knob {knob}; rebuild with prepare_tactics")
            if previous is None or previous[1] != labels:
                self.changes.append({"video_seconds": round(video, 2), "minute": round(minute, 2),
                                     "team_id": self.team_ids[index], "score": list(score),
                                     "phases": labels, "values": values})
            self.current[index] = (values, labels)
