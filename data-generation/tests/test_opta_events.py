"""Derived Opta-style events from synthetic native rows. Rare cases never enter the viewer's match."""

from pathlib import Path
import unittest

from grf_demo.opta import credit_offsides, export, type_id
from grf_demo.telemetry import TelemetryAdapter, opta_xy

# Riverton Rovers (team 0, engine ids 11-21) attack +x in the first half; United (team 1, ids 0-10) attack -x.
# As in the native runtime, contacts/last_touch/ball_retainer use [team, id]; owner uses [team, slot].
HOME_KEEPER, AWAY_KEEPER = [0, 11], [1, 0]


def players(**at):
    """Everyone parked far apart unless placed: at={'0-3': (x, y)}."""
    items = []
    for team in (0, 1):
        for slot in range(11):
            default = (-50 if slot == 0 else -30 + slot * 2, -30 + slot * 5) if team == 0 else \
                      (50 if slot == 0 else 30 - slot * 2, 30 - slot * 5)
            x, y = at.get(f"{team}-{slot}", default)
            items.append({"team": team, "id": slot + 11 if team == 0 else slot, "index": slot, "position_m": [x, y, 0],
                          "possession_ms": 0})
    return items


def frame(ms=0, **changes):
    return {
        "kind": "frame", "telemetry_version": 2, "physics_ms": ms, "match_ms": ms, "phase": 1,
        "in_play": True, "set_piece": False, "score": [0, 0], "owner": [-1, -1], "last_touch": None,
        "ball_position_m": [0, 0, 0], "ball_velocity_mps": [0, 0, 0], "restart_active": False,
        "restart_mode": 0, "restart_team": -1, "restart_id": 0, "players": players(), **changes,
    }


def touch(ms, player, function=4, **changes):
    return {**frame(ms), "kind": "touch", "player": player, "function": function,
            "requested_function": function, "touch_type": 0, "touch_body_part": "right_foot", **changes}


class OptaEventTests(unittest.TestCase):
    def setUp(self):
        self.adapter = TelemetryAdapter()
        self.feed(frame(0))

    def feed(self, row):
        self.adapter.consume(row, row["physics_ms"] / 1000)

    def events(self, kind):
        return [e for e in self.adapter.canonical_events() if e["typeName"] == kind]

    def owned(self, start, end, owner, flip=None):
        """10 ms native frames; `flip` gives one frame of tackler ownership, as GRF does."""
        for ms in range(start, end, 10):
            self.feed(frame(ms, owner=flip if ms == start and flip else owner))

    def test_opta_frame_faces_each_teams_attack(self):
        self.assertEqual(opta_xy([55, -36, 0], 1), (100.0, 0.0))
        self.assertEqual(opta_xy([55, -36, 0], -1), (0.0, 100.0))
        self.feed(touch(100, [0, 12], ball_position_m=[27.5, 0, 0]))
        self.feed(touch(500, [0, 13], 2, ball_position_m=[30, 0, 0]))
        event = self.events("pass")[0]
        self.assertEqual((event["x"], event["y"]), (75.0, 50.0))

    def test_fast_opponent_contact_on_pass_is_interception(self):
        self.feed(touch(100, [0, 12], ball_position_m=[0, 0, 0]))
        self.feed(frame(890, ball_position_m=[11.9, 0, 0], ball_velocity_mps=[9, 0, 0]))
        # Contact rows carry the post-contact ball: a trapped pass is still an interception.
        self.feed(touch(900, [1, 4], 2, ball_position_m=[12, 0, 0], ball_velocity_mps=[0.5, 0, 0]))
        self.assertEqual(self.events("pass")[0]["outcome"], "failure")
        self.assertEqual(self.events("interception")[0]["playerId"], "forgeham-4")
        self.assertEqual(self.events("ball_recovery"), [])

    def test_contact_next_to_passer_is_blocked_pass(self):
        self.feed(touch(100, [0, 12], ball_position_m=[0, 0, 0]))
        self.feed(frame(290, ball_position_m=[1.4, 0, 0], ball_velocity_mps=[12, 0, 0]))
        self.feed(touch(300, [1, 4], 2, ball_position_m=[1.5, 0, 0], ball_velocity_mps=[-3, 0, 0]))
        self.assertEqual(len(self.events("blocked_pass")), 1)
        self.assertEqual(self.events("interception"), [])

    def test_dying_ball_is_recovered_only_if_kept(self):
        self.feed(touch(100, [0, 12]))
        self.feed(frame(1490, ball_position_m=[20, 0, 0], ball_velocity_mps=[2, 0, 0]))
        # A dying ball played on first time at speed is still a recovery, not an interception.
        self.feed(touch(1500, [1, 4], 2, ball_position_m=[20, 0, 0], ball_velocity_mps=[15, 0, 0]))
        self.assertEqual(self.events("interception"), [])
        self.assertEqual(self.events("ball_recovery"), [])  # Pending until United keep it.
        self.feed(touch(2000, [1, 4], 2))
        self.assertEqual(self.events("ball_recovery")[0]["playerId"], "forgeham-4")

    def test_tackle_needs_established_possession_and_records_dispossessed(self):
        self.owned(100, 600, [0, 1])
        self.feed(touch(600, [1, 4], 11, touch_type=2))
        self.owned(610, 800, [1, 4])
        self.feed(touch(800, [1, 4], 2))  # The tackler's team plays on: won, not a recovery.
        tackle = self.events("tackle")[0]
        self.assertEqual((tackle["playerId"], tackle["outcome"]), ("forgeham-4", "success"))
        self.assertEqual(self.events("dispossessed")[0]["playerId"], "riverton-1")
        self.assertEqual(self.events("ball_recovery"), [])

    def test_loose_ball_contest_is_not_a_tackle(self):
        self.owned(100, 200, [0, 1])  # Owner has held the ball for 100 ms.
        self.feed(touch(200, [1, 4], 11, touch_type=2))
        self.owned(210, 800, [1, 4])
        self.assertEqual(self.events("tackle"), [])

    def test_contested_header_is_an_aerial_pair(self):
        close = players(**{"0-2": (10, 0), "1-4": (11, 0.5)})
        self.feed(frame(100, players=close))
        self.feed(touch(200, [0, 13], 7, requested_function=7, touch_type=1, touch_body_part="head",
                        ball_position_m=[10, 0, 2.0], players=close))
        won, lost = self.events("aerial")
        self.assertEqual((won["playerId"], won["outcome"]), ("riverton-2", "success"))
        self.assertEqual((lost["playerId"], lost["outcome"]), ("forgeham-4", "failure"))

    def test_beating_a_goal_side_defender_is_take_on_and_challenge(self):
        before = players(**{"0-9": (10, 0), "1-4": (11.2, 0.3)})
        after = players(**{"0-9": (13, 0), "1-4": (11.5, 0.5)})
        self.feed(frame(1000, owner=[0, 9], players=before))
        self.feed(frame(1600, owner=[0, 9], players=after))
        self.assertEqual(self.events("take_on")[0]["playerId"], "riverton-9")
        self.assertEqual(self.events("challenge")[0]["playerId"], "forgeham-4")

    def test_targetless_ball_from_own_third_under_pressure_is_clearance(self):
        pressed = players(**{"0-4": (-45, 0), "1-2": (-41, 0)})
        self.feed(frame(100, players=pressed))
        self.feed(touch(200, [0, 15], 6, ball_position_m=[-45, 0, 0], players=pressed))
        self.feed(touch(2000, [1, 2], 2, ball_position_m=[5, 0, 0], ball_velocity_mps=[3, 0, 0]))
        clearance = self.events("clearance")[0]
        self.assertEqual((clearance["playerId"], clearance["outcome"]), ("riverton-4", "failure"))
        self.assertEqual(self.events("pass"), [])
        self.assertEqual(self.events("interception"), [])

    def test_ball_over_touchline_and_defender_over_byline(self):
        self.feed(frame(100, last_touch=[0, 14]))
        self.feed(frame(110, in_play=False, last_touch=[0, 14], ball_position_m=[10, 36.4, 0]))
        self.feed(frame(700, in_play=False, last_touch=[0, 14]))
        lost, won = self.events("out")
        self.assertEqual((lost["teamId"], lost["outcome"], won["teamId"]), ("riverton", "failure", "forgeham"))
        self.assertEqual((lost["x"], won["x"]), (59.1, 40.9))  # Mirrored frames.
        self.feed(frame(200, last_touch=[0, 15]))
        self.feed(frame(210, in_play=False, last_touch=[0, 15], ball_position_m=[-55.5, 10, 0]))
        self.feed(frame(800, in_play=False, last_touch=[0, 15]))
        conceded, awarded = self.events("corner_awarded")
        self.assertEqual((conceded["playerId"], awarded["teamId"]), ("riverton-4", "forgeham"))

    def test_offside_decision_marks_pass_and_last_defender(self):
        self.feed(touch(100, [0, 12]))
        self.feed({**frame(300), "kind": "decision", "decision": "offside", "player": [0, 13],
                   "related_player": None, "card": 0})
        self.assertEqual({"type": "offsidePass", "value": True}, self.events("pass")[0]["qualifiers"][-1])
        provoked = self.events("offside_provoked")[0]
        self.assertEqual(provoked["teamId"], "forgeham")
        self.assertEqual(provoked["playerId"], "forgeham-1")  # Deepest outfield United player.

    def test_offside_pass_is_credited_to_the_offside_team(self):
        def event(n, kind, team, qualifiers=(), **extra):
            return {"eventId": f"e{n}", "typeName": kind, "teamId": team, "playerId": f"{team}-{n}", "x": 50.0 + n,
                    "y": 40.0, "qualifiers": list(qualifiers), "outcome": None, **extra}
        flag = {"type": "offsidePass", "value": True}
        events = [event(1, "pass", "a", [flag], outcome="failure"), event(2, "offside", "a"),     # kept
                  event(3, "touch", "b", [{"type": "bodyPart", "value": "head"}]),
                  event(4, "pass", "a", [flag], outcome="failure"), event(5, "offside", "b"),     # wrong team
                  event(6, "touch", "a"), event(7, "offside", "a")]                                # no pass
        out = credit_offsides(events)
        offside = [(e["eventId"], e["teamId"], e["playerId"]) for e in out if type_id(e) == 2]
        self.assertEqual(offside, [("e1", "a", "a-1"), ("e5", "b", "b-3"), ("e7", "a", "a-6")])
        self.assertEqual(sum(e["typeName"] == "offside" for e in out), 3)
        synthetic = out[4]  # Sent with the call: e5's id and time, the touch's player and place.
        self.assertEqual((synthetic["eventId"], synthetic["x"], synthetic["outcome"]), ("e5", 53.0, "failure"))
        self.assertEqual([q["type"] for q in synthetic["qualifiers"]], ["bodyPart", "endX", "endY", "offsidePass"])
        self.assertEqual((out[3]["eventId"], type_id(out[3])), ("e4", 1))  # The other team's pass stays a pass.

    def test_keeper_parry_that_stays_out_is_save_and_parry_that_goes_in_is_goal(self):
        self.feed(touch(100, [0, 20], 8, ball_position_m=[40, 0, 0]))
        self.feed(frame(390, ball_position_m=[52.8, 1, 0.5], ball_velocity_mps=[20, 0, 0]))
        self.feed(touch(400, AWAY_KEEPER, 9, touch_type=2, ball_position_m=[53, 1, 0.5],
                        ball_velocity_mps=[-6, 0, 1]))  # Contact rows carry the rebound.
        self.feed(frame(2100))
        shot, save = self.events("shot")[0], self.events("save")[0]
        self.assertEqual((shot["outcome"], save["playerId"]), ("saved", "forgeham-0"))
        self.assertIn({"type": "saveType", "value": "parried"}, save["qualifiers"])
        self.setUp()
        self.feed(touch(100, [0, 20], 8, ball_position_m=[40, 0, 0]))
        self.feed(frame(390, ball_position_m=[52.8, 1, 0.5], ball_velocity_mps=[20, 0, 0]))
        self.feed(touch(400, AWAY_KEEPER, 9, touch_type=2, ball_position_m=[53, 1, 0.5],
                        ball_velocity_mps=[-6, 0, 1]))  # Contact rows carry the rebound.
        self.feed(frame(500, score=[1, 0], last_touch=[1, 0]))
        self.assertEqual((self.events("shot"), self.events("save")), ([], []))
        self.assertEqual(len(self.events("goal")), 1)

    def test_caught_shot_is_one_save_not_also_a_pickup(self):
        self.feed(touch(100, [0, 20], 8, ball_position_m=[40, 0, 0]))
        self.feed(frame(390, ball_position_m=[52.8, 1, 0.5], ball_velocity_mps=[20, 0, 0]))
        self.feed(touch(400, AWAY_KEEPER, 9, touch_type=2, ball_position_m=[53, 1, 0.5],
                        ball_velocity_mps=[-6, 0, 1]))  # Contact rows carry the rebound.
        self.feed(frame(450, ball_retainer=AWAY_KEEPER))
        self.assertIn({"type": "saveType", "value": "caught"}, self.events("save")[0]["qualifiers"])
        self.assertEqual(self.events("keeper_pickup"), [])

    def test_outfield_block_is_blocked_attempt_with_defensive_block(self):
        self.feed(touch(100, [0, 20], 8, ball_position_m=[40, 0, 0]))
        self.feed(touch(200, [1, 4], 2, touch_type=2, ball_position_m=[42, 0, 0]))
        self.feed(frame(400, in_play=False))
        self.assertEqual(self.events("shot")[0]["outcome"], "blocked")
        self.assertIn({"type": "defensiveBlock", "value": True}, self.events("save")[0]["qualifiers"])

    def test_wide_attempt_records_goal_mouth_and_post_rebound_is_woodwork(self):
        self.feed(touch(100, [0, 20], 8, ball_position_m=[40, 0, 0]))
        self.feed(frame(500, ball_position_m=[55.2, 6, 0.4]))
        miss = self.events("shot")[0]
        self.assertEqual(miss["outcome"], "off_target")
        self.assertIn({"type": "goalMouthY", "value": 58.3}, miss["qualifiers"])
        self.setUp()
        self.feed(touch(100, [0, 20], 8, ball_position_m=[40, 0, 0]))
        self.feed(frame(400, ball_position_m=[54.8, 3.6, 0.5], ball_velocity_mps=[20, 0, 0]))
        self.feed(frame(410, ball_position_m=[54.6, 3.6, 0.5], ball_velocity_mps=[-8, 0, 0]))
        self.assertEqual(self.events("shot")[0]["outcome"], "post")

    def test_assist_situation_and_defensive_error(self):
        self.feed(touch(100, [1, 2], ball_position_m=[40, 0, 0]))  # United pass in their own third.
        self.feed(touch(900, [0, 18], 2, ball_position_m=[35, 0, 0], ball_velocity_mps=[-9, 0, 0]))
        self.feed(touch(1200, [0, 18], 4, ball_position_m=[38, 0, 0]))
        self.feed(touch(1800, [0, 20], 2, ball_position_m=[45, 0, 0]))
        self.feed(touch(2000, [0, 20], 8, ball_position_m=[45, 0, 0]))
        self.feed(frame(2400, in_play=False))
        shot = {q["type"]: q["value"] for q in self.events("shot")[0]["qualifiers"]}
        assist = self.events("pass")[1]
        self.assertEqual(shot["assistEventId"], assist["eventId"])
        self.assertEqual(shot["situation"], "regular_play")
        error = self.events("error")[0]
        self.assertEqual(error["playerId"], "forgeham-2")
        self.assertIn({"type": "leadsTo", "value": "shot"}, error["qualifiers"])

    def test_goal_is_not_also_an_out(self):
        self.feed(touch(100, [0, 20], 8, ball_position_m=[44, 0, 0]))
        self.feed(frame(400, in_play=False, last_touch=[0, 20], ball_position_m=[55.4, 1, 0.3]))
        self.feed(frame(420, in_play=False, score=[1, 0], last_touch=[0, 20], ball_position_m=[55.8, 1, 0.3]))
        self.feed(frame(1500, in_play=False, score=[1, 0], last_touch=[0, 20]))
        self.assertEqual(self.events("out"), [])
        self.assertEqual(len(self.events("goal")), 1)

    def test_whistled_challenge_is_a_foul_not_a_tackle(self):
        self.owned(100, 600, [0, 1])
        self.feed(touch(600, [1, 4], 13, touch_type=2))
        self.owned(610, 650, [0, 1], flip=[1, 4])  # Native flicker, then the whistle.
        self.feed({**frame(655), "kind": "decision", "decision": "foul", "player": [1, 4],
                   "related_player": [0, 12], "card": 0})
        self.feed(frame(700, in_play=False))
        self.assertEqual(len(self.events("foul")), 1)
        self.assertEqual((self.events("tackle"), self.events("dispossessed")), ([], []))

    def test_owner_who_keeps_the_ball_was_not_tackled(self):
        self.owned(100, 600, [0, 1])
        self.feed(touch(600, [1, 4], 11, touch_type=2))
        self.owned(610, 2700, [0, 1], flip=[1, 4])
        self.assertEqual((self.events("tackle"), self.events("dispossessed")), ([], []))

    def test_tackle_that_runs_to_the_owners_team_mate_is_outcome_zero(self):
        self.owned(100, 600, [0, 1])
        self.feed(touch(600, [1, 4], 11, touch_type=2))
        self.owned(610, 900, [-1, -1], flip=[1, 4])
        self.feed(touch(900, [0, 13], 2))
        self.assertEqual([e["outcome"] for e in self.events("tackle")], ["failure"])

    def test_ball_crossing_inside_the_native_frame_is_a_goal_not_also_a_miss(self):
        for crossing in ([55.25, 3.68, 1.0], [55.25, 1.0, 2.47]):
            with self.subTest(crossing=crossing):
                self.setUp()
                self.feed(touch(100, [0, 20], 8, ball_position_m=[44, 0, 0]))
                self.feed(frame(400, ball_position_m=crossing))
                self.feed(frame(420, score=[1, 0], last_touch=[0, 20], ball_position_m=crossing))
                self.assertEqual((self.events("shot"), len(self.events("goal"))), ([], 1))

    def test_rebound_attempt_keeps_the_first_attempt_and_its_save(self):
        self.feed(touch(100, [0, 20], 8, ball_position_m=[40, 0, 0]))
        self.feed(frame(390, ball_position_m=[52.8, 1, 0.5], ball_velocity_mps=[20, 0, 0]))
        self.feed(touch(400, AWAY_KEEPER, 9, touch_type=2, ball_position_m=[53, 1, 0.5]))
        self.feed(touch(900, [0, 20], 8, ball_position_m=[48, 2, 0]))
        self.feed(frame(1300, in_play=False))
        self.assertEqual([e["outcome"] for e in self.events("shot")], ["saved", "off_target"])
        self.assertEqual(len(self.events("save")), 1)

    def test_keeper_tipping_a_wide_attempt_is_not_on_target(self):
        self.feed(touch(100, [0, 20], 8, ball_position_m=[40, 0, 0]))
        self.feed(frame(390, ball_position_m=[52.8, 3, 1.0], ball_velocity_mps=[20, 8, 0]))
        self.feed(touch(400, AWAY_KEEPER, 9, touch_type=2, ball_position_m=[53, 3.3, 1.0]))
        self.feed(frame(2000))
        self.assertEqual(self.events("shot")[0]["outcome"], "off_target")
        self.assertIn({"type": "fromShotOffTarget", "value": True}, self.events("save")[0]["qualifiers"])

    def test_same_team_free_kick_starts_a_set_piece_possession(self):
        self.feed(touch(100, [0, 18], 2))
        before = self.adapter.possession_id
        restart = dict(set_piece=True, restart_active=True, restart_mode=3, restart_team=0, restart_id=9)
        self.feed(touch(1000, [0, 18], 6, ball_position_m=[20, 0, 0], **restart))
        free_kick = self.events("free_kick")[0]
        self.assertEqual(free_kick["possessionId"], before + 1)
        self.feed(touch(2000, [0, 20], 8, ball_position_m=[45, 0, 0]))
        self.feed(frame(2400, in_play=False))
        self.assertIn({"type": "situation", "value": "set_piece"}, self.events("shot")[0]["qualifiers"])

    def test_event_clock_matches_the_packaged_strip(self):
        from grf_demo.package import broadcast_clock
        self.feed(frame(2_950_000, phase=2))
        self.feed(touch(3_015_500, [0, 13], 2, phase=2))
        event = self.events("touch")[0]
        seconds = broadcast_clock(3015.5, [0, 2950])
        self.assertEqual((event["timeMin"], event["timeSec"]), (seconds // 60, seconds % 60))

    def test_score_before_whistle_is_not_an_out(self):
        self.feed(touch(100, [0, 20], 8, ball_position_m=[44, 0, 0]))
        self.feed(frame(400, score=[1, 0], last_touch=[0, 20], ball_position_m=[55.4, 1, 0.3]))
        self.feed(frame(420, in_play=False, score=[1, 0], last_touch=[0, 20], ball_position_m=[55.8, 1, 0.3]))
        self.feed(frame(2000, in_play=False, score=[1, 0], last_touch=[0, 20]))
        self.assertEqual((self.events("out"), len(self.events("goal"))), ([], 1))

    def test_out_after_post_whistle_contacts_keeps_delivery_order(self):
        self.feed(frame(100, last_touch=[0, 14]))
        self.feed(frame(110, in_play=False, last_touch=[0, 14], ball_position_m=[10, 36.4, 0]))
        self.feed(touch(300, [1, 4], 2, in_play=False))  # Fetching the ball after the whistle.
        self.feed(frame(700, in_play=False, last_touch=[0, 14]))
        times = [e["videoSeconds"] for e in self.adapter.canonical_events()]
        self.assertEqual(times, sorted(times))
        self.assertEqual(self.events("out")[0]["x"], 59.1)  # Located where it left the pitch.

    def test_big_chance_needs_clear_sight_of_goal(self):
        clear = players(**{"1-3": (40, 20), "1-4": (40, -20)})
        self.feed(frame(90, players=clear))
        self.feed(touch(100, [0, 20], 8, ball_position_m=[47, 0, 0], players=clear))
        self.feed(frame(500, in_play=False))
        blocked = players(**{"1-3": (50, 0.5), "1-4": (40, -20)})
        self.feed(frame(590, players=blocked))
        self.feed(touch(600, [0, 20], 8, ball_position_m=[47, 0, 0], players=blocked))
        self.feed(frame(900, in_play=False))
        flags = [{"type": "bigChance", "value": True} in e["qualifiers"] for e in self.events("shot")]
        self.assertEqual(flags, [True, False])

    def test_set_piece_situation_is_limited_to_the_delivery_phase(self):
        restart = dict(set_piece=True, restart_active=True, restart_mode=4, restart_team=0, restart_id=3)
        self.feed(touch(100, [0, 18], 6, ball_position_m=[55, 36, 0], **restart))
        self.feed(touch(15000, [0, 20], 8, ball_position_m=[45, 0, 0]))
        self.feed(frame(15500, in_play=False))
        self.assertIn({"type": "situation", "value": "regular_play"}, self.events("shot")[0]["qualifiers"])

    def test_every_emitted_qualifier_is_accepted_downstream(self):
        root = Path(__file__).resolve().parents[2]
        # MatchEvent v2's consumer model (strict: unknown qualifiers are rejected).
        import ast
        import re
        from feed.adapters.recordings import QUALIFIERS
        from grf_demo.capabilities import capabilities
        literals = {}
        for node in ast.parse((root / "user-backend/backend/models/events.py").read_text()).body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Subscript):
                values = node.value.slice.elts if isinstance(node.value.slice, ast.Tuple) else []
                literals[node.targets[0].id] = {v.value for v in values if isinstance(v, ast.Constant)}
        source = (Path(__file__).resolve().parents[1] / "grf_demo/telemetry.py").read_text()
        emitted = set(re.findall(r'"type": "([A-Za-z]+)"', source))
        self.assertLessEqual(emitted, set(QUALIFIERS))
        self.assertEqual(set(QUALIFIERS), literals["QualifierType"])  # the feed sends exactly the contract's
        self.assertEqual(set(capabilities(3)["supported_event_types"]), literals["EventType"])

    def test_throw_in_taken_with_a_control_touch_marks_the_delivery(self):
        restart = dict(set_piece=True, restart_active=True, restart_mode=5, restart_team=0, restart_id=4)
        self.feed(touch(100, [0, 14], 2, ball_position_m=[10, -36, 0], **restart))
        self.feed(touch(700, [0, 14], 4, ball_position_m=[10, -35, 0]))
        self.feed(touch(1300, [0, 15], 2, ball_position_m=[15, -30, 0]))
        self.assertIn({"type": "restart", "value": "throw_in"}, self.events("pass")[0]["qualifiers"])
        self.assertEqual(self.events("take_on"), [])

    def test_penalty_flag_uses_the_real_box_in_metres(self):
        foul = lambda ms, at: {**frame(ms, players=players(**{"0-10": at})), "kind": "decision",
                               "decision": "foul", "player": [1, 4], "related_player": [0, 21], "card": 0}
        self.feed(frame(10, players=players(**{"0-10": (37.5, 20.4)})))
        self.feed(foul(20, (37.5, 20.4)))  # Outside: |y| > 20.15 m.
        self.feed(frame(30, players=players(**{"0-10": (40, 10)})))
        self.feed(foul(40, (40, 10)))
        flags = [{"type": "penaltyAwarded", "value": True} in e["qualifiers"] for e in self.events("foul")]
        self.assertEqual(flags, [False, True])

    def test_penalty_flag_is_settled_by_the_restart_taken_next(self):
        def awarded(mode):
            self.setUp()
            self.feed(frame(10, players=players(**{"0-10": (40, 10)})))
            self.feed({**frame(20, players=players(**{"0-10": (40, 10)})), "kind": "decision", "decision": "foul",
                       "player": [1, 4], "related_player": [0, 10], "card": 0})
            if mode:
                self.feed(touch(500, [0, 10], 6, set_piece=True, restart_active=True, restart_mode=mode,
                                restart_team=0, restart_id=9))
            else:  # The recording ends before any restart.
                self.adapter.finish(frame(500), 0.5)
            return [{"type": "penaltyAwarded", "value": True} in e["qualifiers"]
                    for e in self.events("foul") + self.events("foul_won")]
        self.assertEqual(awarded(6), [True, True])
        self.assertEqual(awarded(3), [False, False])  # A free kick: the referee gave no penalty.
        self.assertEqual(awarded(None), [False, False])

    def test_blocked_passer_is_not_credited_with_a_recovery(self):
        self.feed(touch(100, [0, 12], ball_position_m=[0, 0, 0]))
        self.feed(frame(290, ball_position_m=[1.4, 0, 0], ball_velocity_mps=[12, 0, 0]))
        self.feed(touch(300, [1, 4], 2, ball_position_m=[1.5, 0, 0]))
        self.feed(touch(500, [0, 13], 2))  # Riverton Rovers win the deflection back...
        self.feed(touch(1100, [0, 13], 4))  # ...and keep it.
        recoveries = self.events("ball_recovery")
        self.assertEqual([e["playerId"] for e in recoveries], ["riverton-2"])
        self.assertEqual(self.events("touch")[-2]["possessionId"], recoveries[0]["possessionId"])

    def test_unplayed_tackle_falls_back_to_native_ownership_after_two_seconds(self):
        self.owned(100, 600, [0, 1])
        self.feed(touch(600, [1, 4], 11, touch_type=2))
        self.owned(610, 2700, [1, 4])
        self.assertEqual([e["outcome"] for e in self.events("tackle")], ["success"])
        self.setUp()
        self.owned(100, 600, [0, 1])
        self.feed(touch(600, [1, 4], 11, touch_type=2))
        self.owned(610, 2700, [-1, -1], flip=[1, 4])
        self.assertEqual([e["outcome"] for e in self.events("tackle")], ["failure"])

    def test_events_stay_in_delivery_order(self):
        self.test_assist_situation_and_defensive_error()
        times = [e["videoSeconds"] for e in self.adapter.canonical_events()]
        self.assertEqual(times, sorted(times))


class F24ExportTests(unittest.TestCase):
    def test_types_qualifiers_and_per_team_counters(self):
        adapter = TelemetryAdapter()
        feed = lambda row: adapter.consume(row, row["physics_ms"] / 1000)
        feed(frame(0))
        feed(touch(100, [0, 12], ball_position_m=[0, 0, 0], touch_body_part="head", function=7,
                   requested_function=4, touch_type=1))
        feed(touch(600, [0, 20], 2, ball_position_m=[40, 0, 0]))
        feed(touch(800, [0, 20], 8, ball_position_m=[40, 0, 0]))
        feed(frame(1200, ball_position_m=[55.3, 6, 0.4]))
        document = export({"match_id": "m", "events": adapter.canonical_events()})
        rows = document["events"]
        self.assertEqual([r["type_id"] for r in rows[:2]], [34, 34])
        by_type = {r["type_id"]: r for r in rows}
        head_pass, miss = by_type[1], by_type[13]
        ids = {q["qualifier_id"] for q in head_pass["qualifiers"]}
        self.assertTrue({3, 140, 141, 212, 213, 56, 210} <= ids)
        self.assertEqual(head_pass["outcome"], 1)
        self.assertTrue({20, 22, 29, 55, 102, 103} <= {q["qualifier_id"] for q in miss["qualifiers"]})
        self.assertEqual(miss["outcome"], 0)
        starts = [r for r in rows if r["type_id"] == 32]
        self.assertEqual({r["team_id"] for r in starts}, {"riverton", "forgeham"})
        self.assertTrue(document["synthetic"])


if __name__ == "__main__":
    unittest.main()
