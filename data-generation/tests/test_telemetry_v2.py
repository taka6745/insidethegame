"""Rare native facts are synthetic test inputs, never injected into recorded matches."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grf_demo.telemetry import TelemetryAdapter


def frame(ms=0, **changes):
    return {
        "kind": "frame", "telemetry_version": 2,
        "physics_ms": ms, "match_ms": ms, "phase": 1,
        "in_play": True, "set_piece": False, "score": [0, 0],
        "owner": [-1, -1], "last_touch": None, "ball_position_m": [0, 0, 0],
        "restart_active": False, "restart_mode": 0, "restart_team": -1,
        "restart_id": 0,
        "players": [{"team": team, "id": team * 11 + slot, "index": slot}
                    for team in (0, 1) for slot in range(11)],
        **changes,
    }


def touch(ms=100, player=None, function=4, **changes):
    return {
        **frame(ms), "kind": "touch", "player": player or [0, 1],
        "function": function, "requested_function": function,
        "touch_type": 0, "touch_body_part": "right_foot", **changes,
    }


def decision(ms=100, kind="foul", **changes):
    return {
        **frame(ms), "kind": "decision", "decision": kind,
        "player": [0, 1], "related_player": [1, 12], "card": 0, **changes,
    }


def qualifiers(event):
    return {q["type"]: q["value"] for q in event["qualifiers"]}


class TelemetryV2Tests(unittest.TestCase):
    def setUp(self):
        self.adapter = TelemetryAdapter()
        self.adapter.consume(frame(), 0)

    def feed(self, row):
        self.adapter.consume(row, row["physics_ms"] / 1000)

    def events(self, kind):
        return [event for event in self.adapter.canonical_events() if event["typeName"] == kind]

    def test_header_distribution_intent_is_one_pass_not_a_shot(self):
        for requested in (4, 5, 6):
            with self.subTest(requested=requested):
                self.setUp()
                self.feed(touch(function=7, requested_function=requested, touch_type=1,
                                touch_body_part="head"))
                self.feed(touch(300, [0, 2], 2, ball_position_m=[3, 4, 0]))
                passes = self.events("pass")
                self.assertEqual(len(passes), 1)
                self.assertEqual(passes[0]["playerId"], "chelsea-1")
                self.assertEqual(passes[0]["outcome"], "success")
                self.assertEqual(qualifiers(passes[0])["bodyPart"], "head")
                self.assertEqual(qualifiers(passes[0])["distanceMetres"], 5)
                self.assertEqual(self.events("shot"), [])

    def test_native_pass_and_shot_functions_with_head_contact(self):
        self.feed(touch(function=4, touch_type=1, touch_body_part="head"))
        self.feed(touch(500, [0, 2], 8, touch_type=1, touch_body_part="head"))
        self.assertEqual(qualifiers(self.events("pass")[0])["bodyPart"], "head")
        self.assertEqual(qualifiers(self.events("shot")[0])["bodyPart"], "head")

    def test_header_attempt_becomes_one_goal_and_preserves_head_evidence(self):
        self.feed(touch(function=7, requested_function=8, touch_type=1))
        self.feed(frame(500, score=[1, 0], last_touch=[0, 1]))
        self.assertEqual(self.events("shot"), [])
        goals = self.events("goal")
        self.assertEqual(len(goals), 1)
        self.assertEqual(qualifiers(goals[0])["bodyPart"], "head")
        self.assertIn("sourceShotEventId", qualifiers(goals[0]))

    def test_teammate_deflection_goal_does_not_inherit_shooters_head(self):
        self.feed(touch(function=8, touch_type=1, touch_body_part="head"))
        self.feed(touch(300, [0, 2], 9, touch_type=2, touch_body_part="right_foot"))
        self.feed(frame(500, score=[1, 0], last_touch=[0, 2]))
        goal = self.events("goal")[0]
        self.assertEqual(goal["playerId"], "chelsea-2")
        self.assertNotIn("bodyPart", qualifiers(goal))
        self.assertIn("sourceShotEventId", qualifiers(goal))
        self.assertEqual(self.events("shot"), [])
        self.assertNotIn("goal", self.adapter.capabilities()["body_part_event_types"])

    def test_deliberate_teammate_head_touch_uses_actual_scorer_body_part(self):
        self.feed(touch(function=8, touch_body_part="right_foot"))
        self.feed(touch(300, [0, 2], 2, touch_type=1, touch_body_part="head"))
        self.feed(frame(500, score=[1, 0], last_touch=[0, 2]))
        goal = self.events("goal")[0]
        self.assertEqual(goal["playerId"], "chelsea-2")
        self.assertEqual(qualifiers(goal)["bodyPart"], "head")
        self.assertNotIn("sourceShotEventId", qualifiers(goal))

    def test_unknown_header_intent_is_only_a_headed_contact(self):
        self.feed(touch(function=7, requested_function=7, touch_type=1))
        self.feed(touch(500, [0, 2], 2))
        self.assertEqual(qualifiers(self.events("touch")[0])["bodyPart"], "head")
        self.assertEqual(self.events("pass"), [])
        self.assertEqual(self.events("shot"), [])

    def test_accidental_contact_does_not_borrow_animation_body_part_or_attempt(self):
        self.feed(touch(function=8, touch_type=2, touch_body_part="head"))
        self.assertEqual(qualifiers(self.events("touch")[0]), {})
        self.assertEqual(self.events("shot"), [])

    def test_shin_and_forearm_do_not_claim_exact_foot_or_hand_contact(self):
        expected = {
            "left_foot": "left_foot", "right_foot": "right_foot",
            "left_hand": "hand", "right_hand": "hand",
            "left_lowerleg": "other", "right_lowerleg": "other",
            "left_lowerarm": "other", "right_lowerarm": "other",
        }
        for part, category in expected.items():
            with self.subTest(part=part):
                self.setUp()
                self.feed(touch(function=8, touch_body_part=part))
                self.assertEqual(qualifiers(self.events("shot")[0])["bodyPart"], category)

    def test_awarded_restart_is_not_counted_without_executed_contact(self):
        for mode in range(1, 7):
            with self.subTest(mode=mode):
                self.feed(frame(mode * 100, in_play=False, restart_active=True,
                                restart_mode=mode, restart_team=0, restart_id=mode))
        self.assertEqual([e["typeName"] for e in self.adapter.events], ["period_start"])

    def test_taken_restarts_are_separate_facts_deduplicated_by_restart_id(self):
        kinds = {2: "goal_kick", 3: "free_kick", 4: "corner", 5: "throw_in", 6: "penalty"}
        for mode, kind in kinds.items():
            with self.subTest(mode=mode):
                self.setUp()
                common = dict(set_piece=True, restart_active=True, restart_mode=mode,
                              restart_team=0, restart_id=123)
                self.feed(touch(100, **common))
                self.feed(touch(110, **common))  # repeated native callback
                self.feed(touch(500, function=2, **common))  # later touch, same restart
                self.assertEqual(len(self.events(kind)), 1)
                self.assertEqual(self.events(kind)[0]["playerId"], "chelsea-1")

    def test_restart_requires_active_buffer_set_piece_and_correct_team(self):
        for change in ({"restart_active": False}, {"set_piece": False}, {"restart_team": 1}):
            with self.subTest(change=change):
                self.setUp()
                common = dict(set_piece=True, restart_active=True, restart_mode=4,
                              restart_team=0, restart_id=123)
                self.feed(touch(**{**common, **change}))
                self.assertEqual(self.events("corner"), [])

    def test_corner_delivery_pass_retains_restart_qualifier(self):
        self.feed(touch(set_piece=True, restart_active=True, restart_mode=4,
                        restart_team=0, restart_id=123))
        self.feed(touch(500, [0, 2], 2))
        self.assertEqual(qualifiers(self.events("pass")[0]).get("restart"), "corner")

    def test_penalty_attempt_is_one_shot_with_penalty_context(self):
        self.feed(touch(function=8, set_piece=True, restart_active=True,
                        restart_mode=6, restart_team=0, restart_id=123))
        self.assertEqual(len(self.events("penalty")), 1)
        self.assertEqual(len(self.events("shot")), 1)
        self.assertEqual(qualifiers(self.events("shot")[0])["restart"], "penalty")
        self.assertEqual(self.events("goal"), [])

    def test_kickoff_waits_for_first_deliberate_contact_after_native_ready(self):
        self.feed(decision(kind="kick_off_ready", player=None, restart_team=1))
        self.assertEqual(self.events("kick_off"), [])
        self.feed(touch(200, [1, 12], 4, touch_type=2))
        self.assertEqual(self.events("kick_off"), [])
        self.feed(touch(300, [1, 12], 4))
        self.feed(touch(310, [1, 12], 4))
        kickoffs = self.events("kick_off")
        self.assertEqual(len(kickoffs), 1)
        self.assertEqual(kickoffs[0]["teamId"], "manutd")
        self.assertEqual(kickoffs[0]["playerId"], "manutd-1")
        self.feed(touch(700, [1, 13], 2))
        self.assertEqual(qualifiers(self.events("pass")[0])["restart"], "kick_off")

    def test_initial_whistle_before_capture_still_yields_one_kickoff(self):
        self.adapter = TelemetryAdapter()
        self.feed(frame(50, initial_kickoff_team=0))
        self.feed(frame(60, initial_kickoff_team=0))
        self.assertEqual(self.events("kick_off"), [])
        self.feed(touch(100))
        self.feed(touch(110))
        self.assertEqual(len(self.events("kick_off")), 1)
        self.assertEqual(self.events("kick_off")[0]["playerId"], "chelsea-1")
        self.feed(frame(500, initial_kickoff_team=0))
        self.feed(touch(600))
        self.assertEqual(len(self.events("kick_off")), 1)

    def test_stoppage_cancels_pending_kickoff(self):
        self.feed(decision(kind="kick_off_ready", player=None, restart_team=0))
        self.feed(frame(200, in_play=False))
        self.feed(frame(300))
        self.feed(touch(400))
        self.assertEqual(self.events("kick_off"), [])

    def test_keeper_retention_is_one_claim_per_transition_not_a_save(self):
        self.feed(touch(100, [1, 11], 9, touch_type=2))
        self.assertEqual(self.events("keeper_claim"), [])
        self.feed(frame(110, ball_retainer=[1, 11]))
        self.feed(frame(120, ball_retainer=[1, 11]))
        self.feed(frame(130, ball_retainer=[1, 11]))
        self.assertEqual(len(self.events("keeper_claim")), 1)
        self.assertEqual(self.events("keeper_claim")[0]["playerId"], "manutd-0")
        self.feed(frame(200, ball_retainer=None))
        self.feed(frame(300, ball_retainer=[1, 11]))
        self.assertEqual(len(self.events("keeper_claim")), 2)
        self.assertEqual(self.events("save"), [])

    def test_outfield_retention_and_unused_catch_function_are_not_keeper_claims(self):
        self.feed(frame(100, ball_retainer=[0, 1]))
        self.feed(touch(200, [0, 0], 10, touch_type=1, touch_body_part="right_hand"))
        self.assertEqual(self.events("keeper_claim"), [])

    def test_referee_foul_links_victim_and_does_not_invent_offside_or_restart(self):
        row = decision()
        self.feed(row)
        self.feed(row)
        self.assertEqual(len(self.events("foul")), 1)
        self.assertEqual(self.events("foul")[0]["playerId"], "chelsea-1")
        self.assertEqual(self.events("foul_won")[0]["playerId"], "manutd-1")
        self.assertEqual(qualifiers(self.events("foul_won")[0])["relatedEventId"],
                         self.events("foul")[0]["eventId"])
        self.assertEqual(self.events("offside"), [])
        self.assertEqual(self.events("free_kick"), [])

    def test_offside_whistle_is_not_a_foul(self):
        self.feed(decision(kind="offside"))
        self.assertEqual(len(self.events("offside")), 1)
        self.assertEqual(self.events("foul"), [])
        self.assertEqual(self.events("foul_won"), [])
        self.assertEqual(self.events("card"), [])

    def test_offside_receiver_does_not_complete_pass_or_create_attempt(self):
        self.feed(touch(100, [0, 1], 4))
        self.feed(decision(300, "offside", player=[0, 2], in_play=False))
        self.feed(touch(300, [0, 2], 8, in_play=False))
        self.assertEqual(len(self.events("offside")), 1)
        self.assertEqual(len(self.events("touch")), 2)
        self.assertEqual(len(self.events("pass")), 1)
        self.assertEqual(self.events("pass")[0]["outcome"], "failure")
        self.assertEqual(self.events("shot"), [])
        self.feed(frame(310, in_play=False))
        self.assertEqual(len(self.events("pass")), 1)

    def test_stoppage_contact_does_not_start_a_pass_for_later_live_resolution(self):
        self.feed(touch(100, [0, 1], 4, in_play=False))
        self.feed(frame(110, in_play=False))
        self.feed(frame(700))
        self.feed(touch(800, [0, 2], 2))
        self.assertEqual(len(self.events("touch")), 2)
        self.assertEqual(self.events("pass"), [])
        self.assertEqual(self.events("shot"), [])

    def test_restart_held_before_whistle_is_only_contact_until_live_execution(self):
        common = dict(set_piece=True, restart_active=True, restart_mode=4,
                      restart_team=0, restart_id=123)
        self.feed(touch(100, function=4, in_play=False, **common))
        self.assertEqual(len(self.events("touch")), 1)
        self.assertEqual(self.events("corner"), [])
        self.assertEqual(self.events("pass"), [])
        self.feed(touch(500, function=4, **common))
        self.feed(touch(700, [0, 2], 2))
        self.assertEqual(len(self.events("corner")), 1)
        self.assertEqual(len(self.events("pass")), 1)
        self.assertEqual(self.events("pass")[0]["outcome"], "success")
        self.assertEqual(qualifiers(self.events("pass")[0])["restart"], "corner")

    def test_whistle_transition_is_not_coalesced_with_stopped_contact(self):
        common = dict(set_piece=True, restart_active=True, restart_mode=3,
                      restart_team=0, restart_id=123)
        self.feed(touch(100, function=4, in_play=False, **common))
        self.feed(touch(110, function=4, **common))
        self.feed(touch(400, [0, 2], 2))
        self.assertEqual(len(self.events("free_kick")), 1)
        self.assertEqual(len(self.events("pass")), 1)
        self.assertEqual(self.events("pass")[0]["outcome"], "success")

    def test_yellow_second_yellow_and_red_have_distinct_meaning(self):
        for raw, colour in ((0, None), (1, "yellow"), (2, "second_yellow"), (3, "red")):
            with self.subTest(card=raw):
                self.setUp()
                self.feed(decision(card=raw))
                cards = self.events("card")
                if colour is None:
                    self.assertEqual(cards, [])
                else:
                    self.assertEqual(len(cards), 1)
                    self.assertEqual(cards[0]["outcome"], colour)
                    self.assertEqual(qualifiers(cards[0])["relatedEventId"], self.events("foul")[0]["eventId"])

    def test_continuous_contact_callbacks_do_not_inflate_touch_counts(self):
        for ms in (100, 110, 250, 400, 690):
            self.feed(touch(ms, function=2))
        self.assertEqual(len(self.events("touch")), 1)
        self.feed(touch(1000, function=2))
        self.assertEqual(len(self.events("touch")), 2)

    def test_half_and_full_time_boundaries_are_exact(self):
        self.feed(frame(359_990))
        self.feed(frame(360_000, phase=2, in_play=False))
        self.feed(frame(360_010, phase=2))
        self.adapter.finish(frame(720_000, phase=2), 720)
        starts, ends = self.events("period_start"), self.events("period_end")
        self.assertEqual([(e["periodId"], e["timeMin"]) for e in starts], [(1, 0), (2, 45)])
        self.assertEqual([(e["periodId"], e["timeMin"]) for e in ends], [(1, 45), (2, 90)])

    def test_short_capture_does_not_invent_full_time(self):
        self.adapter.finish(frame(10_000), 10)
        self.assertEqual(self.events("period_end"), [])

    def test_capabilities_do_not_claim_unobserved_event_semantics(self):
        capabilities = self.adapter.capabilities()
        supported = set(capabilities["supported_event_types"])
        self.assertTrue({"foul", "offside", "corner", "card"} <= supported)
        self.assertTrue({"save", "tackle", "interception", "substitution", "injury", "var"}.isdisjoint(supported))
        self.assertFalse(capabilities["shot_outcomes"])
        self.assertEqual(capabilities["restart_events"], "taken")
        self.assertEqual(capabilities["body_part_event_types"], ["pass", "shot", "goal"])
        self.assertEqual(capabilities["possession_basis"], "confirmed_native_ownership")

    def test_missing_contact_body_evidence_removes_complete_dataset_promise(self):
        self.feed(touch(touch_body_part=""))
        self.feed(touch(500, [0, 2], 2))
        self.assertNotIn("pass", self.adapter.capabilities()["body_part_event_types"])
        self.feed(frame(600, score=[1, 0], last_touch=None))
        self.assertNotIn("goal", self.adapter.capabilities()["body_part_event_types"])

    def test_legacy_rows_do_not_claim_new_instrumentation(self):
        adapter = TelemetryAdapter()
        old = frame()
        old.pop("telemetry_version")
        adapter.consume(old, 0)
        self.assertEqual(adapter.events, [])
        self.assertEqual(adapter.capabilities()["supported_event_types"], ["touch", "pass", "shot", "goal"])


if __name__ == "__main__":
    unittest.main()
