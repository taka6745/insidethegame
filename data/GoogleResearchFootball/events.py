"""Turn instrumented engine contacts/state into explicitly defined football events."""

import math
from collections import Counter

FUNCTIONS = [
    "none",
    "movement",
    "ball_control",
    "trap",
    "short_pass",
    "long_pass",
    "high_pass",
    "header",
    "shot",
    "deflect",
    "catch",
    "interfere",
    "trip",
    "sliding",
    "special",
]
MODES = ["normal", "kickoff", "goal_kick", "free_kick", "corner", "throw_in", "penalty"]


def norm(v):
    return math.sqrt(sum(x * x for x in v))


class Events:
    def __init__(self, emit):
        self.emit = emit
        self.counts = Counter()
        self.sequence = 0
        self.previous = None
        self.pending_pass = None
        self.last_shot = None
        self.last_contact = None
        self.passes = []
        self.players = {}

    def event(self, kind, row, **fields):
        self.sequence += 1
        item = {
            "id": self.sequence,
            "type": kind,
            "physics_ms": row["physics_ms"],
            "match_ms": row["match_ms"],
            **fields,
        }
        self.counts[kind] += 1
        self.emit(item)
        return item

    def finish_pass(self, row, outcome, receiver=None, completed=None):
        p = self.pending_pass
        if p is None:
            return
        self.advance_pass(row)
        p.update(
            outcome=outcome,
            completed=completed,
            receiver=receiver,
            end_physics_ms=row["physics_ms"],
            end_match_ms=row["match_ms"],
            end_position_m=row["ball_position_m"],
            duration_s=(row["physics_ms"] - p["physics_ms"]) / 1000,
        )
        p["displacement_m"] = norm(
            [
                b - a
                for a, b in zip(p["start_position_m"][:2], row["ball_position_m"][:2])
            ]
        )
        p["mean_path_speed_mps"] = (
            p["flight_path_m"] / p["duration_s"] if p["duration_s"] else None
        )
        self.event(
            "pass_result",
            row,
            **{k: v for k, v in p.items() if k not in ("physics_ms", "match_ms")},
        )
        self.passes.append(dict(p))
        self.pending_pass = None

    def advance_pass(self, row):
        if self.pending_pass:
            p = self.pending_pass
            p["flight_path_m"] += norm(
                [a - b for a, b in zip(row["ball_position_m"], self.pass_position)]
            )
            self.pass_position = row["ball_position_m"]

    def consume(self, row):
        if row["kind"] == "touch":
            fn = FUNCTIONS[row["function"]]
            actor = row["player"]
            intentional = row["touch_type"] in (0, 1)
            if self.pending_pass:
                if intentional:
                    same_team = actor[0] == self.pending_pass["passer"][0]
                    completed = same_team and actor != self.pending_pass["passer"]
                    self.finish_pass(
                        row,
                        "completed"
                        if completed
                        else "self_recovery"
                        if same_team
                        else "opponent_control",
                        actor,
                        completed,
                    )
                else:
                    self.advance_pass(row)
                    self.pending_pass["deflections"].append(
                        {"player": actor, "physics_ms": row["physics_ms"]}
                    )
            touch = self.event(
                "ball_touch",
                row,
                player=actor,
                function=fn,
                touch_type=row["touch_type"],
                position_m=row["ball_position_m"],
                velocity_mps=row["ball_velocity_mps"],
                speed_mps=norm(row["ball_velocity_mps"]),
            )
            if intentional and self.last_contact and actor[0] != self.last_contact[0]:
                self.event(
                    "recovery",
                    row,
                    player=actor,
                    previous_touch_player=self.last_contact,
                    basis="intentional touch after other-team contact; not a certified tackle",
                )
            self.last_contact = actor
            if fn in ("short_pass", "long_pass", "high_pass") and intentional:
                v = row["ball_velocity_mps"]
                p = self.event(
                    "pass",
                    row,
                    passer=actor,
                    pass_type=fn,
                    intended_receiver=row["target_player"],
                    forced_receiver=row["forced_target_player"],
                    start_position_m=row["ball_position_m"],
                    launch_velocity_mps=v,
                    launch_speed_mps=norm(v),
                    launch_speed_kmh=norm(v) * 3.6,
                    direction_degrees=math.degrees(math.atan2(v[1], v[0])),
                    elevation_degrees=math.degrees(math.atan2(v[2], norm(v[:2]))),
                    source_touch_id=touch["id"],
                )
                self.pending_pass = {
                    k: v for k, v in p.items() if k not in ("id", "type")
                }
                self.pending_pass.update(
                    pass_id=p["id"], flight_path_m=0.0, deflections=[]
                )
                self.pass_position = row["ball_position_m"]
                self.last_shot = None
            elif fn == "shot" and intentional:
                self.last_shot = self.event(
                    "shot",
                    row,
                    player=actor,
                    position_m=row["ball_position_m"],
                    launch_velocity_mps=row["ball_velocity_mps"],
                    speed_mps=norm(row["ball_velocity_mps"]),
                    source_touch_id=touch["id"],
                )
            elif fn in ("header", "catch", "deflect", "sliding", "interfere"):
                self.event(
                    fn + "_contact", row, player=actor, source_touch_id=touch["id"]
                )
            return
        old = self.previous
        if old:
            if row["physics_ms"] - old["physics_ms"] != 10:
                self.event(
                    "clock_jump",
                    row,
                    previous_physics_ms=old["physics_ms"],
                    delta_ms=row["physics_ms"] - old["physics_ms"],
                )
            if row["game_mode"] != old["game_mode"]:
                self.event(
                    "game_mode_change",
                    row,
                    previous=MODES[old["game_mode"]],
                    current=MODES[row["game_mode"]],
                )
            if row["in_play"] != old["in_play"]:
                self.event("play_started" if row["in_play"] else "play_stopped", row)
                if not row["in_play"]:
                    self.finish_pass(row, "play_stopped", completed=False)
            if row["phase"] != old["phase"]:
                self.event(
                    "phase_change", row, previous=old["phase"], current=row["phase"]
                )
            if row["score"] != old["score"]:
                self.event(
                    "goal",
                    row,
                    score=row["score"],
                    previous_score=old["score"],
                    last_touch=row["last_touch"],
                    preceding_shot_id=self.last_shot["id"] if self.last_shot else None,
                )
                self.last_shot = None
            if row["owner"] != old["owner"]:
                self.event(
                    "possession_change",
                    row,
                    previous=old["owner"],
                    current=row["owner"],
                    identity="team/index; -1 means no engine-confirmed owner",
                )
            if self.pending_pass and row["in_play"] and old["in_play"]:
                self.advance_pass(row)
        for p in row["players"]:
            key = (p["team"], p["id"])
            prev = self.players.get(key)
            if prev:
                if p["function"] != prev["function"] and p["function"] not in (0, 1):
                    self.event(
                        "action_started",
                        row,
                        player=list(key),
                        function=FUNCTIONS[p["function"]],
                        basis="animation state; not necessarily executed ball contact",
                    )
                if p["has_card"] != prev["has_card"]:
                    self.event(
                        "card_flag_change",
                        row,
                        player=list(key),
                        has_card=p["has_card"],
                    )
                if p["active"] != prev["active"]:
                    self.event(
                        "active_status_change",
                        row,
                        player=list(key),
                        active=p["active"],
                    )
            self.players[key] = p
        self.previous = row

    def finish(self):
        if self.previous:
            self.finish_pass(self.previous, "unresolved_at_export_end")
