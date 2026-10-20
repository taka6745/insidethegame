"""GRF adapter. Executed contacts and referee decisions are facts; animation starts are not events.

Derived Opta-style events (shot outcomes, saves, tackles, interceptions, clearances, aerials,
take-ons, recoveries, outs) follow the documented rules in docs/opta-events.md, applied to
native 100 Hz tracking. Pitch locations use Opta's 0-100 frame for the acting team.
"""

import math
from .roster import TEAMS, player_id
from .contact import RESTARTS, action_function, contact_qualifiers
from .capabilities import capabilities

HALF_X, HALF_Y = 55.0, 36.0  # Inside the touchlines and goal lines.
POST_Y, BAR_Z = 3.7, 2.5  # Native goal frame (Match::CheckForGoal); the line plane is x = 55.17.
GOAL_LINE = 55.17
KEEPER = 0  # Roster slot of each goalkeeper.
PASSES, TACKLES = (4, 5, 6), (11, 13)


def opta_xy(position, attack):
    """Opta frame: acting team attacks towards x=100; y=0 is that team's right touchline."""
    return (round(50 + 50 * attack * position[0] / HALF_X, 1),
            round(50 + 50 * attack * position[1] / HALF_Y, 1))


class TelemetryAdapter:
    def __init__(self, half_seconds=2700):
        self.half_seconds = half_seconds
        self.events = []
        self.players = {}
        self.previous = None
        self.pending_pass = None
        self.pending_shot = None
        self.pending_tackle = None
        self.pending_punch = None
        self.pending_out = None
        self.pending_miscontrol = None
        self.pending_recovery = None
        self.last_contact = None
        self.last_body_contact = None
        self.possession = [0.0, 0.0]
        self.last_flush = 0
        self.possession_samples = []
        self.version = 1
        self.restarts = set()
        self.decisions = set()
        self.pending_kickoff = None
        self.period_start = {}
        self.attack = {}
        self.possession_team = None
        self.possession_id = 0
        self.possession_start = None
        self.received = {}
        self.turnover = None
        self.take_on = None
        self.slots = {}
        self.ids = {}
        self.previous_video = 0.0
        self.last_goal_ms = -10**9
        self.pending_restart = None  # (taker, kind, possession): a control touch may precede the delivery.
        self.restart_ms = -10**9
        self.current_owner, self.owner_since = [-1, -1], 0

    # Clock and location -------------------------------------------------

    def period(self, row):
        return 1 if row["phase"] <= 1 else 2

    def seconds(self, row, video):
        """Broadcast clock on the video timeline: runs through dead play; second half starts at 45:00.

        Physics time can jump during native restarts, so the clock follows what viewers see,
        exactly like the packaged score strip.
        """
        period = self.period(row)
        start = self.period_start.get(period, video)
        offset = 0 if period == 1 else self.half_seconds
        return offset + int(max(0.0, video - start))

    def attack_of(self, team, period):
        default = (1 if team == 0 else -1) * (1 if period == 1 else -1)
        return self.attack.get((team, period), default)

    def xy(self, team, row, position=None):
        position = position or row.get("ball_position_m")
        if team not in (0, 1) or not position:
            return None, None
        return opta_xy(position, self.attack_of(team, self.period(row)))

    def emit(self, kind, row, video, actor=None, team=None, qualifiers=(), outcome=None, at=None):
        team = actor[0] if team is None and actor else team
        if team not in (None, 0, 1):
            return None
        seconds = self.seconds(row, video)
        x, y = self.xy(team, row, at)
        event = {
            "eventId": f"grf-che-utd-{len(self.events) + 1}",
            "matchId": "product-demo-match",
            "revision": 1,
            "sequence": len(self.events) + 1,
            "typeName": kind,
            "teamId": TEAMS[team]["id"] if team is not None else None,
            "playerId": self.players.get(tuple(actor)) if actor else None,
            "periodId": self.period(row),
            "timeMin": seconds // 60,
            "timeSec": seconds % 60,
            "x": x,
            "y": y,
            "qualifiers": list(qualifiers),
            "outcome": outcome,
            "videoSeconds": round(video, 3),
            "possessionId": self.possession_id or None,
            "synthetic": True,
        }
        self.events.append(event)
        return event

    def owner(self, row):
        """Native owner is [team, slot]; contacts use [team, engine id]."""
        team, slot = (row or {}).get("owner") or [-1, -1]
        return [team, self.ids.get((team, slot), slot)] if team in (0, 1) else [-1, -1]

    def is_keeper(self, actor):
        return self.slots.get(tuple(actor)) == KEEPER

    def players_in(self, row):
        return (row or {}).get("players") or []

    def position(self, player, row=None):
        for item in self.players_in(row or self.previous):
            if [item["team"], item["id"]] == list(player) and "position_m" in item:
                return item["position_m"]
        return None

    def nearest_teammate(self, passer, point, limit):
        return any(item["team"] == passer[0] and [item["team"], item["id"]] != list(passer)
                   and "position_m" in item and math.dist(point[:2], item["position_m"][:2]) <= limit
                   for item in self.players_in(self.previous))

    def nearest_opponent(self, actor, row, limit, outfield=False):
        here = self.position(actor, row)
        if not here:
            return None
        best = None
        for item in self.players_in(row):
            if item["team"] == actor[0] or "position_m" not in item or (outfield and item["index"] == KEEPER):
                continue
            distance = math.dist(here[:2], item["position_m"][:2])
            if distance <= limit and (best is None or distance < best[0]):
                best = (distance, [item["team"], item["id"]])
        return best and best[1]

    # Passes -------------------------------------------------------------

    def is_clearance(self, row, actor):
        """A target-less long, high or headed ball from the defensive third."""
        x, _ = self.xy(actor[0], row)
        return (x is not None and x <= 25 and (action_function(row) in (5, 6) or row["function"] == 7)
                and not row.get("target_player") and not row.get("forced_target_player")
                and self.nearest_opponent(actor, self.previous, 8.0) is not None)

    def finish_pass(self, row, video, actor=None, stopped=False, offside=False):
        if not self.pending_pass:
            return None
        start, passer = self.pending_pass
        self.pending_pass = None
        success = actor is not None and actor[0] == passer[0] and actor != passer
        distance = math.dist(start["ball_position_m"][:2], row["ball_position_m"][:2])
        qualifiers = contact_qualifiers(start) + [{"type": "distanceMetres", "value": round(distance, 3)}]
        x0, y0 = self.xy(passer[0], start)
        x1, y1 = self.xy(passer[0], row)
        if x0 is not None:
            angle = math.atan2(y0 - y1, x1 - x0) % (2 * math.pi)  # Clockwise from forward, Opta Q213.
            qualifiers += [{"type": "endX", "value": x1}, {"type": "endY", "value": y1},
                           {"type": "angle", "value": round(angle, 3)}]
            if distance > 32:
                qualifiers.append({"type": "longBall", "value": True})
            if x0 >= 66.7 and (y0 < 21.1 or y0 > 78.9) and x1 >= 83 and 21.1 < y1 < 78.9:
                qualifiers.append({"type": "cross", "value": True})
            if abs(y1 - y0) >= 50:
                qualifiers.append({"type": "switchOfPlay", "value": True})
        if action_function(start) == 6:
            qualifiers.append({"type": "chipped", "value": True})
        if offside:
            qualifiers.append({"type": "offsidePass", "value": True})
        kind = "clearance" if start.get("event_clearance") else "pass"
        outcome = "success" if success else "failure" if actor or stopped else None
        event = self.emit(kind, start, video, passer, qualifiers=qualifiers, outcome=outcome)
        # Pass events are timestamped at resolution so live delivery never reveals the future.
        event.update(self.when(row, video))
        if success:
            self.received[tuple(actor)] = (event, row["physics_ms"], self.possession_id)
        elif outcome == "failure" and actor is not None and actor[0] != passer[0] and x0 is not None and x0 < 33.3:
            self.turnover = (passer, event, row["physics_ms"])
        return event

    def when(self, row, video):
        seconds = self.seconds(row, video)
        return {"periodId": self.period(row), "timeMin": seconds // 60,
                "timeSec": seconds % 60, "videoSeconds": round(video, 3)}

    # Shots --------------------------------------------------------------

    def start_shot(self, row, video, actor, qualifiers):
        if self.pending_shot:
            self.settle_shot(row, video)  # A rebound attempt never erases the first one.
        team, period = actor[0], self.period(row)
        x, y = self.xy(team, row)
        extra = []
        received = self.received.get(tuple(actor))
        if received and received[2] == self.possession_id and row["physics_ms"] - received[1] <= 8000:
            extra.append({"type": "assistEventId", "value": received[0]["eventId"]})
        start = self.possession_start
        restart = next((q["value"] for q in qualifiers if q["type"] == "restart"), None)
        situation = "regular_play"
        if restart == "penalty":
            situation = "penalty"
        elif restart == "free_kick":
            situation = "direct_free_kick"
        elif (start and start["restart"] in ("corner", "free_kick", "throw_in")
              and row["physics_ms"] - start["ms"] <= 10000):
            # Opta ties set-piece situations to the delivery phase, not the whole possession.
            situation = {"corner": "from_corner", "free_kick": "set_piece", "throw_in": "from_throw_in"}[start["restart"]]
        elif start and start["x"] is not None and start["x"] < 40 and row["physics_ms"] - start["ms"] <= 12000:
            situation = "fast_break"
        extra.append({"type": "situation", "value": situation})
        if self.big_chance(actor, row, self.attack_of(team, period)):
            extra.append({"type": "bigChance", "value": True})
        self.pending_shot = {"row": row, "video": video, "actor": actor, "qualifiers": qualifiers + extra,
                             "side": self.attack_of(team, period), "contact": None}

    def big_chance(self, actor, row, side):
        """Within 11 m of goal, no outfield defender within 2 m or between the ball and either post."""
        ball = row["ball_position_m"]
        goal = (HALF_X * side, 0.0)
        if math.dist(ball[:2], goal) > 11 or self.nearest_opponent(actor, self.previous, 2.0, outfield=True):
            return False
        for item in self.players_in(self.previous):
            if item["team"] == actor[0] or item["index"] == KEEPER or "position_m" not in item:
                continue
            px, py = item["position_m"][:2]
            depth = (px - ball[0]) * side
            reach = abs(goal[0] - ball[0])
            if 0 < depth < reach:
                # Lateral limits of the shooting triangle at this depth.
                fraction = depth / reach
                low = ball[1] + (-POST_Y - ball[1]) * fraction
                high = ball[1] + (POST_Y - ball[1]) * fraction
                if min(low, high) - 0.5 <= py <= max(low, high) + 0.5:
                    return False
        return True

    def finish_shot(self, row, video, outcome, extra=(), keeper=None):
        shot = self.pending_shot
        self.pending_shot = None
        event = self.emit("shot", shot["row"], shot["video"], shot["actor"],
                          qualifiers=shot["qualifiers"] + [{"type": "shotOutcome", "value": outcome}, *extra],
                          outcome=outcome)
        event.update(self.when(row, video))
        if keeper is not None:
            save = [{"type": "relatedEventId", "value": event["eventId"]}]
            if keeper["keeper"]:
                save.append({"type": "saveType", "value": "caught" if keeper["caught"] else "parried"})
                if outcome == "off_target":
                    save.append({"type": "fromShotOffTarget", "value": True})
            else:
                save.append({"type": "defensiveBlock", "value": True})
            # Located where the ball was stopped; timestamped when the attempt settled.
            self.emit("save", row, video, keeper["actor"], qualifiers=save, outcome="success",
                      at=keeper["row"]["ball_position_m"])
        self.error_before(event, row, video, "shot")
        return event

    def goal_mouth(self, crossing):
        """Opta Q102/Q103: y on the pitch scale; z is about 38 at the crossbar."""
        y, z = crossing
        return [{"type": "goalMouthY", "value": round(50 + 50 * y * self.pending_shot["side"] / HALF_Y, 1)},
                {"type": "goalMouthZ", "value": round(z / BAR_Z * 38, 1)}]

    def track_shot(self, row, video):
        shot = self.pending_shot
        old = self.previous
        side = shot["side"]
        ball, before = row["ball_position_m"], old["ball_position_m"]
        contact = shot["contact"]
        if ball[0] * side > GOAL_LINE:
            inside = abs(ball[1]) < POST_Y and ball[2] < BAR_Z
            # Native scoring registers a frame or two after the line; wait inside the frame.
            if not inside or row["physics_ms"] - shot["row"]["physics_ms"] > 4000:
                if contact:
                    self.settle_shot(row, video)
                else:
                    self.finish_shot(row, video, "off_target", self.goal_mouth(row["ball_position_m"][1:3]))
        elif (not contact and before[0] * side >= HALF_X - 0.6 and old["ball_velocity_mps"][0] * side > 0
              and row["ball_velocity_mps"][0] * side < 0
              and (abs(abs(ball[1]) - POST_Y) < 0.4 or abs(ball[2] - BAR_Z) < 0.35)):
            self.finish_shot(row, video, "post", [{"type": "woodwork", "value": True}])
        elif not row["in_play"] or row["phase"] != old["phase"]:
            self.settle_shot(row, video)
        elif contact and row["physics_ms"] - contact["row"]["physics_ms"] > 1500:
            self.settle_shot(row, video)
        elif row["physics_ms"] - shot["row"]["physics_ms"] > 3000:
            self.settle_shot(row, video)

    def settle_shot(self, row, video):
        """A keeper or defender contact is a save or block only once the ball has not gone in."""
        contact = self.pending_shot["contact"]
        if not contact:
            self.finish_shot(row, video, "off_target")
        elif contact["keeper"]:
            outcome = "saved" if contact["on_target"] else "off_target"
            mouth = self.goal_mouth(contact["crossing"]) if contact["crossing"] else []
            self.finish_shot(row, video, outcome, mouth, keeper=contact)
        else:
            self.finish_shot(row, video, "blocked", keeper=contact)

    def shot_contact(self, row, video, actor, intentional):
        shot = self.pending_shot
        if actor[0] != shot["actor"][0]:
            if not shot["contact"]:
                keeper = self.is_keeper(actor)
                crossing = self.projection()
                shot["contact"] = {"keeper": keeper, "actor": actor, "row": row, "crossing": crossing,
                                   "on_target": bool(crossing) and abs(crossing[0]) <= POST_Y and crossing[1] <= BAR_Z,
                                   "caught": keeper and row["function"] == 10}
            if intentional and not self.is_keeper(actor):
                self.settle_shot(row, video)  # The defender has the ball.
                return True
            return self.is_keeper(actor)
        if actor != shot["actor"] and intentional:
            # A new deliberate teammate action ends the attempt. Deflections do not.
            self.settle_shot(row, video)
        return False

    def projection(self):
        """Goal-line crossing projected from the frame before a contact, or None if not goalward.

        Contact telemetry is recorded after the native touch, so its velocity is the rebound.
        """
        side = self.pending_shot["side"]
        before = self.previous or {}
        ball, velocity = before.get("ball_position_m"), before.get("ball_velocity_mps") or [0, 0, 0]
        if not ball or velocity[0] * side <= 0:
            return None
        t = (HALF_X * side - ball[0]) / velocity[0]
        return ball[1] + velocity[1] * t, max(0.0, ball[2] + velocity[2] * t)

    def error_before(self, shot, row, video, result):
        """A defensive-half turnover directly followed by the opponent's attempt."""
        turnover = self.turnover
        if not turnover or turnover[0][0] == shot_team(shot) or row["physics_ms"] - turnover[2] > 6000:
            return
        self.turnover = None
        error = self.emit("error", row, video, turnover[0], qualifiers=[
            {"type": "relatedEventId", "value": turnover[1]["eventId"]},
            {"type": "leadsTo", "value": result}])
        error.update(x=turnover[1]["x"], y=turnover[1]["y"])  # Located at the mistake.

    # Contacts -----------------------------------------------------------

    def flush(self, row, video):
        for team, seconds in enumerate(self.possession):
            if seconds:
                self.possession_samples.append(
                    {"video_seconds": round(video, 3), "team_id": TEAMS[team]["id"],
                     "duration_seconds": round(seconds, 3)})
        self.possession = [0.0, 0.0]
        self.last_flush = video

    def gain_possession(self, row, video, actor, restart=None):
        if actor[0] == self.possession_team and not restart:
            return False
        self.possession_team = actor[0]
        self.possession_id += 1
        x, _ = self.xy(actor[0], row)
        self.possession_start = {"ms": row["physics_ms"], "x": x, "restart": restart}
        return True

    def consume(self, row, video):
        self.version = max(self.version, row.get("telemetry_version", 1))
        if row["kind"] == "decision":
            self.consume_decision(row, video)
            return
        if row["kind"] == "touch":
            self.consume_touch(row, video)
            return
        self.consume_frame(row, video)

    def consume_touch(self, row, video):
        actor = row["player"]
        contact = (tuple(actor), row["function"], row["touch_type"], row.get("in_play", True))
        repeated = (self.last_contact and contact == self.last_contact[0]
                    and 0 <= row["physics_ms"] - self.last_contact[1] <= 300)
        self.last_contact = (contact, row["physics_ms"])
        if repeated:
            return
        intentional = row["touch_type"] in (0, 1)
        stopped = not row.get("in_play", True)
        handled = False
        if stopped:
            # Referee decisions run before the contact callback. An offside recipient
            # must not complete the preceding pass or create an attempt after the whistle.
            self.finish_pass(row, video, stopped=True)
            if self.pending_shot:
                self.settle_shot(row, video)
        else:
            if self.pending_shot:
                handled = self.shot_contact(row, video, actor, intentional)
            if intentional or (self.is_keeper(actor) and self.pending_pass and actor[0] != self.pending_pass[1][0]):
                handled = self.contest_pass(row, video, actor) or handled
            if intentional and self.pending_miscontrol:
                loser, event_row, event_video = self.pending_miscontrol
                self.pending_miscontrol = None
                if actor[0] != loser[0]:
                    self.emit("ball_touch", event_row, event_video, loser,
                              outcome="failure").update(self.when(row, video))
        qualifiers = contact_qualifiers(row)
        self.last_body_contact = (tuple(actor), [q for q in qualifiers if q["type"] == "bodyPart"])
        contact = self.emit("touch", row, video, actor, qualifiers=qualifiers)
        if stopped:
            return
        if not intentional:
            if (not self.is_keeper(actor) and actor[0] == self.possession_team and row["function"] not in TACKLES
                    and not self.pending_shot):
                self.pending_miscontrol = (actor, row, video)
            self.tackle(row, video, actor)
            return
        restart = self.consume_restart(row, video, actor, qualifiers)
        if restart:
            self.pending_restart = (tuple(actor), restart, self.possession_id)
            self.restart_ms = row["physics_ms"]
        taker = self.pending_restart
        if taker and (taker[0] != tuple(actor) or taker[2] != self.possession_id
                      or row["physics_ms"] - self.restart_ms > 10000):
            self.pending_restart = taker = None
        if taker and action_function(row) in PASSES + (8,):
            restart = taker[1]  # Opta puts the restart on the taker's delivery, not a control touch.
            self.pending_restart = None
        if restart:
            qualifiers = qualifiers + [{"type": "restart", "value": restart}]
        tackled = False
        if self.pending_tackle and row["physics_ms"] - self.pending_tackle["row"]["physics_ms"] > 50:
            tackled = self.resolve_tackle(row, video, actor)  # The tackler's team playing on is not a recovery.
        tackled = (not handled and self.tackle(row, video, actor)) or tackled
        self.aerial(row, video, actor, qualifiers)
        recovery = self.pending_recovery
        if recovery and actor[0] != recovery[0][0]:
            self.pending_recovery = recovery = None  # The other team played it: nothing was recovered.
        if recovery and row["physics_ms"] - recovery[1]["physics_ms"] > 300:
            self.pending_recovery = None
            if actor[0] == recovery[0][0]:
                # Opta: the recovering team keeps the ball for its next action.
                self.emit("ball_recovery", recovery[1], recovery[2], recovery[0],
                          outcome="success").update(self.when(row, video))
        if self.gain_possession(row, video, actor) and not (handled or tackled or restart):
            if not self.is_keeper(actor) or row["function"] not in (9, 10):
                self.pending_recovery = (actor, row, video)
        contact["possessionId"] = self.possession_id or None  # The gaining contact opens its possession.
        if actor[0] == self.possession_team:
            if self.turnover and self.turnover[0][0] == actor[0]:
                self.turnover = None
        function = action_function(row)
        if function in PASSES:
            start = {**row, "event_restart": restart, "event_clearance": self.is_clearance(row, actor) and not restart}
            self.pending_pass = (start, actor)
        elif function == 8:
            self.start_shot(row, video, actor, qualifiers)
        elif row["function"] == 9 and self.is_keeper(actor) and row["ball_position_m"][2] > 1.5:
            self.pending_punch = (actor, row, video)

    def contest_pass(self, row, video, actor):
        """Resolve a pass in flight; an opponent's first contact is an interception or block."""
        if not self.pending_pass:
            return False
        start, passer = self.pending_pass
        if actor[0] == passer[0]:
            self.finish_pass(row, video, actor)
            return False
        clearance = start.get("event_clearance")
        self.finish_pass(row, video, actor)
        if self.is_keeper(actor) and row["function"] in (9, 10):
            return True  # Keeper retention or punch has its own event.
        close = (row["physics_ms"] - start["physics_ms"] <= 400
                 and math.dist(start["ball_position_m"][:2], row["ball_position_m"][:2]) < 4)
        # Contact rows carry the post-contact velocity; judge the pass from the frame before.
        speed = math.hypot(*((self.previous or row).get("ball_velocity_mps") or [0, 0, 0])[:2])
        if close:
            self.emit("blocked_pass", row, video, actor, outcome="success")
            return True  # The blocker's team gains possession; no recovery or interception is added.
        elif (clearance or self.is_clearance(row, actor) or speed < 8
              or self.nearest_teammate(passer, row["ball_position_m"], 3.0)):
            # Cleared, dying or arriving balls are recovered (Opta ball recovery); an interception
            # cuts out a moving pass before it reaches the passer's team-mate.
            return False
        else:
            self.emit("interception", row, video, actor, outcome="success")
        self.gain_possession(row, video, actor)
        return True

    def tackle(self, row, video, actor):
        """Interfere/sliding contact on an established owner; decided over the following 0.5 s."""
        old = self.previous or {}
        owner = self.owner(old)
        if (row["function"] not in TACKLES or self.is_keeper(actor) or owner[0] not in (0, 1)
                or owner[0] == actor[0] or self.pending_pass or self.pending_tackle):
            return False
        if row["physics_ms"] - self.owner_since < 400:
            return False  # A loose or just-arrived ball is contested, not tackled.
        self.pending_tackle = {"actor": actor, "owner": owner, "row": row, "video": video, "won": 0, "kept": 0}
        return True

    def resolve_tackle(self, row, video, toucher=None):
        """Opta tackle: the ball is taken off its owner; outcome 1 when the tackler's team keeps it
        (or play stops), 0 when it runs loose or to the owner's team-mate. The owner keeping it is
        no tackle. Settled by the next intentional contact; native ownership (which flickers to the
        tackler for a frame on contact) decides only if nobody plays the ball within 2 s. A foul
        whistled first cancels the tackle (see consume_decision). Returns True when won."""
        pending = self.pending_tackle
        actor, owner = pending["actor"], pending["owner"]
        if toucher is not None:
            if toucher[0] == actor[0]:
                won = True
            elif list(toucher) == list(owner):
                self.pending_tackle = None
                return False
            else:
                won = False
        else:
            current = self.owner(row)
            pending["won"] += current[0] == actor[0]
            pending["kept"] += current == list(owner)
            elapsed = row["physics_ms"] - pending["row"]["physics_ms"]
            if row["in_play"] and elapsed < 2000:
                return False
            if row["in_play"] and pending["kept"] >= pending["won"]:
                self.pending_tackle = None
                return False
            won = not row["in_play"] or pending["won"] >= 30
        self.pending_tackle = None
        start, start_video = pending["row"], pending["video"]
        event = self.emit("tackle", start, start_video, actor, outcome="success" if won else "failure")
        event.update(self.when(row, video))
        related = [{"type": "relatedEventId", "value": event["eventId"]}]
        if self.take_on and self.take_on[0] == tuple(owner) and self.take_on[1] == tuple(actor):
            lost = self.emit("take_on", start, start_video, owner, outcome="failure", qualifiers=related)
            self.take_on = None
        else:
            lost = self.emit("dispossessed", start, start_video, owner, outcome="failure", qualifiers=related)
        lost.update(self.when(row, video))
        if won and self.gain_possession(row, video, actor):
            x, _ = self.xy(owner[0], start)
            if x is not None and x < 33.3:
                self.turnover = (owner, lost, row["physics_ms"])
        return won

    def aerial(self, row, video, actor, qualifiers):
        head = any(q["type"] == "bodyPart" and q["value"] == "head" for q in qualifiers)
        if not head or row["ball_position_m"][2] < 1.0:
            return
        opponent = self.nearest_opponent(actor, self.previous, 2.0)
        if opponent:
            won = self.emit("aerial", row, video, actor, outcome="success")
            self.emit("aerial", row, video, opponent, outcome="failure",
                      qualifiers=[{"type": "relatedEventId", "value": won["eventId"]}])

    def scan_take_on(self, row, video):
        """Owner passes a close, goal-side opponent while keeping the ball."""
        owner = self.owner(row)
        if owner[0] not in (0, 1) or not row["in_play"]:
            self.take_on = None
            return
        here = self.position(owner, row)
        if not here:
            return
        side = self.attack_of(owner[0], self.period(row))
        if row["physics_ms"] - self.restart_ms < 3000:
            self.take_on = None  # Players line up close at restarts; that is not a duel.
            return
        if self.take_on and self.take_on[0] != tuple(owner):
            self.take_on = None
        if self.take_on:
            there = self.position(self.take_on[1], row)
            elapsed = row["physics_ms"] - self.take_on[2]
            if there and (here[0] - there[0]) * side > 0.8 and abs(here[1] - there[1]) < 3:
                event = self.emit("take_on", row, video, list(self.take_on[0]), outcome="success")
                self.emit("challenge", row, video, list(self.take_on[1]), outcome="failure",
                          qualifiers=[{"type": "relatedEventId", "value": event["eventId"]}])
                self.take_on = None
            elif elapsed > 2500:
                self.take_on = None
            return
        for item in self.players_in(row):
            if item["team"] == owner[0] or "position_m" not in item:
                continue
            ahead = (item["position_m"][0] - here[0]) * side
            if 0.3 < ahead < 2.0 and abs(item["position_m"][1] - here[1]) < 1.2:
                self.take_on = (tuple(owner), (item["team"], item["id"]), row["physics_ms"])
                return

    # Frames -------------------------------------------------------------

    def consume_frame(self, row, video):
        for player in row["players"]:
            self.players[(player["team"], player["id"])] = player_id(player["team"], player["index"])
            self.slots[(player["team"], player["id"])] = player["index"]
            self.ids[(player["team"], player["index"])] = player["id"]
        old = self.previous
        if not old and row.get("initial_kickoff_team") in (0, 1):
            # Environment creation already blew the opening whistle, but nobody touched the ball.
            self.pending_kickoff = (row["initial_kickoff_team"], row["physics_ms"])
        if row["phase"] in (1, 2) and self.period(row) not in self.period_start:
            self.start_period(row, video)
        retainer = row.get("ball_retainer")
        if self.version >= 2 and retainer and (not old or old.get("ball_retainer") != retainer):
            self.keeper_retention(row, video, retainer)
        if self.version >= 2 and row["phase"] in (1, 2) and (not old or old["phase"] != row["phase"]):
            if old and old["phase"] == 1:
                self.emit("period_end", old, self.previous_video)
            self.emit("period_start", row, video)
        if old:
            self.consume_play(row, video, old)
        self.previous = row
        self.previous_video = video
        if video - self.last_flush >= 1:
            self.flush(row, video)

    def start_period(self, row, video):
        period = self.period(row)
        self.period_start[period] = video
        for item in self.players_in(row):
            if item["index"] == KEEPER and "position_m" in item and item["position_m"][0]:
                self.attack[(item["team"], period)] = -1 if item["position_m"][0] > 0 else 1

    def keeper_retention(self, row, video, retainer):
        if self.players.get(tuple(retainer)) != player_id(retainer[0], KEEPER):
            return
        shot = self.pending_shot
        if shot and shot["contact"] and shot["contact"]["keeper"] and shot["contact"]["actor"] == list(retainer):
            shot["contact"]["caught"] = True
            self.settle_shot(row, video)  # The catch is the save.
            self.gain_possession(row, video, retainer)
            return
        self.pending_punch = None
        old_ball = (self.previous or row)["ball_position_m"]
        kind = "keeper_claim" if old_ball[2] > 1.2 else "keeper_pickup"
        self.emit(kind, row, video, retainer, qualifiers=[{"type": "bodyPart", "value": "hand"}], outcome="success")
        self.gain_possession(row, video, retainer)

    def consume_play(self, row, video, old):
        owner = self.owner(row)
        if owner != self.current_owner:
            self.current_owner, self.owner_since = owner, row["physics_ms"]
        delta = row["physics_ms"] - old["physics_ms"]
        owner = old["owner"][0]
        if delta == 10 and old["in_play"] and owner in (0, 1):
            self.possession[owner] += delta / 1000
        if not row["in_play"] and old["in_play"]:
            self.finish_pass(row, video, stopped=True)
            self.pending_kickoff = None
            self.pending_recovery = None
            if row["physics_ms"] - self.last_goal_ms > 3000:  # A goal is not an out.
                self.pending_out = (row, video)
        for team in (0, 1):
            if row["score"][team] > old["score"][team]:
                self.score(row, video, team)
        if self.pending_shot and row["score"] == old["score"]:
            self.track_shot(row, video)
        if self.pending_tackle:
            self.resolve_tackle(row, video)
        if self.pending_punch and row["physics_ms"] - self.pending_punch[1]["physics_ms"] > 300:
            actor, start, start_video = self.pending_punch
            self.pending_punch = None
            self.emit("punch", start, start_video, actor, outcome="success").update(self.when(row, video))
        if self.pending_miscontrol and row["physics_ms"] - self.pending_miscontrol[1]["physics_ms"] > 1500:
            self.pending_miscontrol = None
        if self.pending_out and row["physics_ms"] - self.pending_out[0]["physics_ms"] >= 500:
            self.out_of_play(*self.pending_out, row, video)  # Native scoring can lag the line.
        if row["physics_ms"] % 40 == 0:
            self.scan_take_on(row, video)

    def score(self, row, video, team):
        actor = row["last_touch"]
        if not actor or actor[0] != team:
            actor = None
        qualifiers = [{"type": "score", "value": "-".join(map(str, row["score"]))}]
        shot = self.pending_shot
        if shot and shot["actor"][0] == team:
            qualifiers += [q for q in shot["qualifiers"] if q["type"] in ("restart", "situation", "assistEventId", "bigChance")]
            qualifiers += self.goal_mouth(row["ball_position_m"][1:3])
        if actor and self.last_body_contact and self.last_body_contact[0] == tuple(actor):
            qualifiers.extend(self.last_body_contact[1])
        at = shot["row"]["ball_position_m"] if shot and actor == shot["actor"] else None
        goal = self.emit("goal", row, video, actor, team, qualifiers=qualifiers, at=at)
        self.last_goal_ms = row["physics_ms"]
        self.pending_shot = None
        self.pending_out = None
        self.error_before(goal, row, video, "goal")

    def out_of_play(self, row, video, now, now_video):
        """Ball over a line: throw-in or goal-kick outs and awarded corners, Opta-paired.

        Located where the ball left the pitch; timestamped now, after any post-whistle contacts.
        """
        self.pending_out = None
        ball, last = row["ball_position_m"], row.get("last_touch")
        if abs(ball[0]) > HALF_X and abs(ball[1]) <= POST_Y and ball[2] <= BAR_Z:
            return  # Inside the goal frame: a goal, whatever order native scoring reports it in.
        if not last or last[0] not in (0, 1):
            return
        other = 1 - last[0]
        if abs(ball[1]) > HALF_Y:
            kind = "out"
        elif abs(ball[0]) > HALF_X:
            end = 1 if ball[0] > 0 else -1
            defending = last[0] if self.attack_of(last[0], self.period(row)) != end else other
            kind = "corner_awarded" if last[0] == defending else "out"
        else:
            return
        lost = self.emit(kind, row, video, last, outcome="failure")
        lost.update(self.when(now, now_video))
        self.emit(kind, row, video, team=other, outcome="success",
                  qualifiers=[{"type": "relatedEventId", "value": lost["eventId"]}]).update(self.when(now, now_video))

    def canonical_events(self):
        return [{**event, "sequence": i + 1} for i, event in enumerate(self.events)]

    def consume_restart(self, row, video, actor, qualifiers):
        if self.pending_kickoff and row.get("in_play"):
            team, _ = self.pending_kickoff
            self.pending_kickoff = None
            if actor[0] == team:
                self.gain_possession(row, video, actor, "kick_off")
                self.emit("kick_off", row, video, actor, qualifiers=qualifiers)
                return "kick_off"
        if not row.get("set_piece") or not row.get("restart_active") or actor[0] != row.get("restart_team"):
            return None
        kind = RESTARTS.get(row.get("restart_mode"))
        key = (row.get("restart_id"), row.get("restart_mode"), row.get("restart_team"))
        if not kind or key in self.restarts:
            return None
        self.restarts.add(key)
        self.gain_possession(row, video, actor, kind)  # Every taken restart starts a possession.
        self.emit(kind, row, video, actor, qualifiers=qualifiers)
        return kind

    def consume_decision(self, row, video):
        key = (row["physics_ms"], row["decision"], tuple(row.get("player") or []))
        if key in self.decisions:
            return
        self.decisions.add(key)
        # Decisions carry no ball state; use the latest frame for location.
        row = {**(self.previous or {"ball_position_m": [0, 0, 0], "players": []}), **row}
        actor = row["player"]
        if row["decision"] == "kick_off_ready":
            self.pending_kickoff = (row["restart_team"], row["physics_ms"])
        elif row["decision"] == "offside":
            self.finish_pass(row, video, stopped=True, offside=True)
            self.emit("offside", row, video, actor)
            self.offside_provoked(row, video, actor)
        elif row["decision"] == "foul":
            if self.pending_tackle and self.pending_tackle["actor"] == list(actor or []):
                self.pending_tackle = None  # A whistled challenge is a foul, not a tackle.
            at = self.position(row["related_player"]) if row.get("related_player") else None
            penalty = self.in_box(row, at, actor)
            extra = [{"type": "penaltyAwarded", "value": True}] if penalty else []
            foul = self.emit("foul", row, video, actor, qualifiers=extra, at=at, outcome="failure")
            related = [{"type": "relatedEventId", "value": foul["eventId"]}]
            if row.get("related_player"):
                self.emit("foul_won", row, video, row["related_player"], qualifiers=related + extra, at=at,
                          outcome="success")
            card = {1: "yellow", 2: "second_yellow", 3: "red"}.get(row.get("card"))
            if card:
                self.emit("card", row, video, actor, qualifiers=related + [{"type": "cardReason", "value": "foul"}],
                          outcome=card, at=at)

    def in_box(self, row, at, actor):
        if not at or not actor:
            return False
        # In metres on GRF's 110x72 pitch, as the native referee decides penalties.
        side = self.attack_of(1 - actor[0], self.period(row))  # Victim's attack.
        return at[0] * side >= HALF_X - 16.5 and abs(at[1]) <= 20.15

    def offside_provoked(self, row, video, actor):
        if not actor:
            return
        defenders = [item for item in self.players_in(self.previous)
                     if item["team"] != actor[0] and item["index"] != KEEPER and "position_m" in item]
        if not defenders:
            return
        side = self.attack_of(defenders[0]["team"], self.period(row))
        last = min(defenders, key=lambda item: item["position_m"][0] * side)
        self.emit("offside_provoked", row, video, [last["team"], last["id"]], outcome="success",
                  at=last["position_m"])

    def finish(self, row, video):
        if self.pending_shot:
            self.finish_shot(row, video, "off_target")
        self.finish_pass(row, video)
        self.flush(row, video)
        if self.version >= 2 and row["match_ms"] >= 2 * self.half_seconds * 1000:
            self.emit("period_end", row, video)

    def capabilities(self):
        result = capabilities(self.version)
        if self.version >= 2:
            # This promise describes the finite recording, including goals with unknown scorers.
            result["body_part_event_types"] = [kind for kind in ("pass", "shot", "goal")
                if all(any(q["type"] == "bodyPart" for q in event["qualifiers"])
                       for event in self.events if event["typeName"] == kind)]
        return result


def shot_team(event):
    return 0 if event["teamId"] == TEAMS[0]["id"] else 1
