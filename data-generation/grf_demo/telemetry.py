"""Small GRF adapter. Executed contacts are facts; animation starts are not events."""

import math
from .roster import TEAMS, player_id
from .contact import RESTARTS, action_function, contact_qualifiers
from .capabilities import capabilities


class TelemetryAdapter:
    def __init__(self):
        self.events = []
        self.players = {}
        self.previous = None
        self.pending_pass = None
        self.last_contact = None
        self.last_body_contact = None
        self.last_shot = None
        self.scored_shot_ids = set()
        self.possession = [0.0, 0.0]
        self.last_flush = 0
        self.possession_samples = []
        self.version = 1
        self.restarts = set()
        self.decisions = set()
        self.pending_kickoff = None

    def emit(
        self, kind, row, video, actor=None, team=None, qualifiers=(), outcome=None
    ):
        team = actor[0] if team is None and actor else team
        if team not in (None, 0, 1):
            return
        seconds = min(5400, int(row["match_ms"] * 7.5 / 1000))
        event = {
            "eventId": f"grf-che-utd-{len(self.events) + 1}",
            "matchId": "product-demo-match",
            "revision": 1,
            "sequence": len(self.events) + 1,
            "typeName": kind,
            "teamId": TEAMS[team]["id"] if team is not None else None,
            "playerId": self.players.get(tuple(actor)) if actor else None,
            "periodId": 1 if row["phase"] <= 1 else 2,
            "timeMin": seconds // 60,
            "timeSec": seconds % 60,
            "qualifiers": list(qualifiers),
            "outcome": outcome,
            "videoSeconds": round(video, 3),
            "synthetic": True,
        }
        self.events.append(event)
        return event

    def finish_pass(self, row, video, actor=None, stopped=False):
        if not self.pending_pass:
            return
        start, passer = self.pending_pass
        success = actor is not None and actor[0] == passer[0] and actor != passer
        distance = math.dist(start["ball_position_m"][:2], row["ball_position_m"][:2])
        self.emit(
            "pass",
            row,
            video,
            passer,
            qualifiers=contact_qualifiers(start) + [{"type": "distanceMetres", "value": round(distance, 3)}],
            outcome="success" if success else "failure" if actor or stopped else None,
        )
        self.pending_pass = None

    def flush(self, row, video):
        for team, seconds in enumerate(self.possession):
            if seconds:
                self.possession_samples.append(
                    {
                        "video_seconds": round(video, 3),
                        "team_id": TEAMS[team]["id"],
                        "duration_seconds": round(seconds, 3),
                    }
                )
        self.possession = [0.0, 0.0]
        self.last_flush = video

    def consume(self, row, video):
        self.version = max(self.version, row.get("telemetry_version", 1))
        if row["kind"] == "decision":
            self.consume_decision(row, video)
            return
        if row["kind"] == "touch":
            actor = row["player"]
            contact = (tuple(actor), row["function"], row["touch_type"], row.get("in_play", True))
            repeated = (
                self.last_contact
                and contact == self.last_contact[0]
                and 0 <= row["physics_ms"] - self.last_contact[1] <= 300
            )
            self.last_contact = (contact, row["physics_ms"])
            if repeated:
                return
            intentional = row["touch_type"] in (0, 1)
            stopped = not row.get("in_play", True)
            if stopped:
                # Referee decisions run before the contact callback. An offside recipient
                # must not complete the preceding pass or create an attempt after the whistle.
                self.finish_pass(row, video, stopped=True)
                self.last_shot = None
            elif intentional:
                # A new deliberate action ends the previous shot. Deflections do not.
                self.last_shot = None
                self.finish_pass(row, video, actor)
            qualifiers = contact_qualifiers(row)
            self.last_body_contact = (tuple(actor), [q for q in qualifiers if q["type"] == "bodyPart"])
            self.emit("touch", row, video, actor, qualifiers=qualifiers)
            if stopped:
                return
            restart = self.consume_restart(row, video, actor, qualifiers) if intentional else None
            if restart:
                qualifiers = qualifiers + [{"type": "restart", "value": restart}]
            function = action_function(row)
            if intentional and function in (4, 5, 6):
                self.pending_pass = ({**row, "event_restart": restart}, actor)
                self.last_shot = None
            elif intentional and function == 8:
                self.last_shot = self.emit("shot", row, video, actor, qualifiers=qualifiers)
            return
        for player in row["players"]:
            self.players[(player["team"], player["id"])] = player_id(
                player["team"], player["index"]
            )
        old = self.previous
        if not old and row.get("initial_kickoff_team") in (0, 1):
            # Environment creation already blew the opening whistle, but nobody touched the ball.
            self.pending_kickoff = (row["initial_kickoff_team"], row["physics_ms"])
        retainer = row.get("ball_retainer")
        if self.version >= 2 and retainer and (not old or old.get("ball_retainer") != retainer):
            if self.players.get(tuple(retainer)) == player_id(retainer[0], 0):
                self.emit("keeper_claim", row, video, retainer, qualifiers=[{"type": "bodyPart", "value": "hand"}])
        if self.version >= 2 and row["phase"] in (1, 2) and (not old or old["phase"] != row["phase"]):
            if old and old["phase"] == 1:
                self.emit("period_end", {**row, "phase": 1, "match_ms": 360_000}, video)
            self.emit("period_start", row, video)
        if old:
            delta = row["physics_ms"] - old["physics_ms"]
            owner = old["owner"][0]
            if delta == 10 and old["in_play"] and owner in (0, 1):
                self.possession[owner] += delta / 1000
            if not row["in_play"] and old["in_play"]:
                self.finish_pass(row, video, stopped=True)
                self.pending_kickoff = None
            for team in (0, 1):
                if row["score"][team] > old["score"][team]:
                    actor = row["last_touch"]
                    if not actor or actor[0] != team:
                        actor = None
                    qualifiers = [
                        {"type": "score", "value": "-".join(map(str, row["score"]))}
                    ]
                    if self.last_shot and self.last_shot["teamId"] == TEAMS[team]["id"]:
                        shot_id = self.last_shot["eventId"]
                        self.scored_shot_ids.add(shot_id)
                        qualifiers.append(
                            {"type": "sourceShotEventId", "value": shot_id}
                        )
                        qualifiers.extend(q for q in self.last_shot["qualifiers"] if q["type"] == "restart")
                    if actor and self.last_body_contact and self.last_body_contact[0] == tuple(actor):
                        qualifiers.extend(self.last_body_contact[1])
                    self.emit("goal", row, video, actor, team, qualifiers=qualifiers)
                    self.last_shot = None
            if not row["in_play"] or row["phase"] != old["phase"]:
                self.last_shot = None
        self.previous = row
        if video - self.last_flush >= 1:
            self.flush(row, video)

    def canonical_events(self):
        """Our contract counts a scored attempt once, as goal. Raw contacts remain archived."""
        events = [
            event
            for event in self.events
            if event["eventId"] not in self.scored_shot_ids
        ]
        return [{**event, "sequence": i + 1} for i, event in enumerate(events)]

    def consume_restart(self, row, video, actor, qualifiers):
        if self.pending_kickoff and row.get("in_play"):
            team, _ = self.pending_kickoff
            self.pending_kickoff = None
            if actor[0] == team:
                self.emit("kick_off", row, video, actor, qualifiers=qualifiers)
                return "kick_off"
        if not row.get("set_piece") or not row.get("restart_active") or actor[0] != row.get("restart_team"):
            return None
        kind = RESTARTS.get(row.get("restart_mode"))
        key = (row.get("restart_id"), row.get("restart_mode"), row.get("restart_team"))
        if not kind or key in self.restarts:
            return None
        self.restarts.add(key)
        self.emit(kind, row, video, actor, qualifiers=qualifiers)
        return kind

    def consume_decision(self, row, video):
        key = (row["physics_ms"], row["decision"], tuple(row.get("player") or []))
        if key in self.decisions:
            return
        self.decisions.add(key)
        actor = row["player"]
        if row["decision"] == "kick_off_ready":
            self.pending_kickoff = (row["restart_team"], row["physics_ms"])
        elif row["decision"] == "offside":
            self.emit("offside", row, video, actor)
        elif row["decision"] == "foul":
            foul = self.emit("foul", row, video, actor)
            related = [{"type": "relatedEventId", "value": foul["eventId"]}]
            if row.get("related_player"):
                self.emit("foul_won", row, video, row["related_player"], qualifiers=related)
            card = {1: "yellow", 2: "second_yellow", 3: "red"}.get(row.get("card"))
            if card:
                self.emit("card", row, video, actor, qualifiers=related, outcome=card)

    def finish(self, row, video):
        self.finish_pass(row, video)
        self.flush(row, video)
        if self.version >= 2 and row["match_ms"] >= 720_000:
            self.emit("period_end", row, video)

    def capabilities(self):
        result = capabilities(self.version)
        if self.version >= 2:
            # This promise describes the finite recording, including goals with unknown scorers.
            result["body_part_event_types"] = [kind for kind in ("pass", "shot", "goal")
                if all(any(q["type"] == "bodyPart" for q in event["qualifiers"])
                       for event in self.canonical_events() if event["typeName"] == kind)]
        return result
