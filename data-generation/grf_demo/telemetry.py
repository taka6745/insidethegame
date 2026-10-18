"""Small GRF adapter. Executed contacts are facts; animation starts are not events."""

import math
from .roster import TEAMS, player_id


class TelemetryAdapter:
    def __init__(self):
        self.events = []
        self.players = {}
        self.previous = None
        self.pending_pass = None
        self.last_contact = None
        self.last_shot = None
        self.scored_shot_ids = set()
        self.possession = [0.0, 0.0]
        self.last_flush = 0
        self.possession_samples = []

    def emit(
        self, kind, row, video, actor=None, team=None, qualifiers=(), outcome=None
    ):
        team = actor[0] if team is None and actor else team
        if team not in (0, 1):
            return
        seconds = min(5400, int(row["match_ms"] * 7.5 / 1000))
        event = {
            "eventId": f"grf-che-utd-{len(self.events) + 1}",
            "matchId": "product-demo-match",
            "revision": 1,
            "sequence": len(self.events) + 1,
            "typeName": kind,
            "teamId": TEAMS[team]["id"],
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
            qualifiers=[{"type": "distanceMetres", "value": round(distance, 3)}],
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
        if row["kind"] == "touch":
            actor = row["player"]
            contact = (tuple(actor), row["function"], row["touch_type"])
            repeated = (
                self.last_contact
                and contact == self.last_contact[0]
                and 0 <= row["physics_ms"] - self.last_contact[1] <= 300
            )
            self.last_contact = (contact, row["physics_ms"])
            if repeated:
                return
            intentional = row["touch_type"] in (0, 1)
            if intentional:
                # A new deliberate action ends the previous shot. Deflections do not.
                self.last_shot = None
                self.finish_pass(row, video, actor)
            qualifiers = (
                [{"type": "bodyPart", "value": "head"}] if row["function"] == 7 else []
            )
            self.emit("touch", row, video, actor, qualifiers=qualifiers)
            if intentional and row["function"] in (4, 5, 6):
                self.pending_pass = (row, actor)
                self.last_shot = None
            elif intentional and row["function"] == 8:
                self.last_shot = self.emit("shot", row, video, actor)
            return
        for player in row["players"]:
            self.players[(player["team"], player["id"])] = player_id(
                player["team"], player["index"]
            )
        old = self.previous
        if old:
            delta = row["physics_ms"] - old["physics_ms"]
            owner = old["owner"][0]
            if delta == 10 and old["in_play"] and owner in (0, 1):
                self.possession[owner] += delta / 1000
            if not row["in_play"] and old["in_play"]:
                self.finish_pass(row, video, stopped=True)
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
