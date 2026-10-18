import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grf_demo.telemetry import TelemetryAdapter
from grf_demo.package import presentation_time


def frame(ms=0, score=None, owner=None, phase=1):
    return {
        "kind": "frame",
        "physics_ms": ms,
        "match_ms": ms,
        "phase": phase,
        "in_play": True,
        "score": score or [0, 0],
        "owner": owner or [-1, -1],
        "last_touch": None,
        "players": [
            {"team": t, "id": i + t * 11, "index": i} for t in (0, 1) for i in range(11)
        ],
        "ball_position_m": [0, 0, 0],
    }


def touch(actor, function=4, ms=100):
    return {
        **frame(ms),
        "kind": "touch",
        "player": actor,
        "function": function,
        "touch_type": 0,
    }


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.adapter = TelemetryAdapter()
        self.adapter.consume(frame(), 0)

    def test_pass_counts_once_and_only_completes_for_different_teammate(self):
        self.adapter.consume(touch([0, 1]), 0.1)
        self.adapter.consume(touch([0, 2], 2, 200), 0.2)
        passes = [e for e in self.adapter.events if e["typeName"] == "pass"]
        self.assertEqual(len(passes), 1)
        self.assertEqual(passes[0]["outcome"], "success")
        self.assertEqual(passes[0]["playerId"], "chelsea-1")
        self.adapter.consume(touch([0, 1]), 0.3)
        self.adapter.consume(touch([1, 12], 2, 400), 0.4)
        self.assertEqual(
            [e["outcome"] for e in self.adapter.events if e["typeName"] == "pass"],
            ["success", "failure"],
        )

    def test_header_is_not_invented_shot(self):
        self.adapter.consume(touch([1, 12], 7), 0.1)
        self.assertEqual([e["typeName"] for e in self.adapter.events], ["touch"])
        self.assertEqual(
            self.adapter.events[0]["qualifiers"],
            [{"type": "bodyPart", "value": "head"}],
        )
        self.assertEqual(self.adapter.events[0]["playerId"], "manutd-1")

    def test_goals_follow_score_not_last_touch_team(self):
        row = frame(100, score=[1, 0])
        row["last_touch"] = [1, 12]
        self.adapter.consume(row, 0.1)
        event = self.adapter.events[0]
        self.assertEqual(event["teamId"], "chelsea")
        self.assertIsNone(event["playerId"])
        self.assertEqual(event["typeName"], "goal")

    def test_possession_excludes_loose_ball_and_clock_jumps(self):
        self.adapter.consume(frame(10, owner=[0, 1]), 0.01)
        self.adapter.consume(frame(20, owner=[0, 1]), 0.02)
        self.adapter.consume(frame(3000, owner=[0, 1]), 3)
        self.assertEqual(
            self.adapter.possession_samples,
            [{"video_seconds": 3, "team_id": "chelsea", "duration_seconds": 0.01}],
        )
        self.assertFalse(self.adapter.events)

    def test_period_clock_and_video_mapping(self):
        row = touch([0, 1], 8, 360_000)
        row["phase"] = 2
        self.adapter.consume(row, 400)
        shot = self.adapter.events[-1]
        self.assertEqual(
            (shot["periodId"], shot["timeMin"], shot["videoSeconds"]), (2, 45, 400)
        )
        self.assertEqual(presentation_time(400, 400, 800), 360)
        self.assertEqual(presentation_time(800, 400, 800), 720)
        self.assertEqual(presentation_time(200, 400, 800), 180)
        with self.assertRaises(ValueError):
            presentation_time(1, 0, 800)

    def test_continuous_physics_contacts_form_one_pass(self):
        self.adapter.consume(touch([0, 1], 4, 100), 0.1)
        for ms in range(110, 310, 10):
            self.adapter.consume(touch([0, 1], 4, ms), ms / 1000)
        self.adapter.consume(touch([0, 2], 2, 500), 0.5)
        passes = [
            event
            for event in self.adapter.canonical_events()
            if event["typeName"] == "pass"
        ]
        self.assertEqual(len(passes), 1)
        self.assertEqual(passes[0]["outcome"], "success")
        self.assertEqual(
            len([e for e in self.adapter.events if e["typeName"] == "touch"]), 2
        )

    def test_scored_shot_is_represented_once_as_goal(self):
        self.adapter.consume(touch([0, 1], 8, 100), 0.1)
        row = frame(200, score=[1, 0])
        row["last_touch"] = [0, 1]
        self.adapter.consume(row, 0.2)
        canonical = self.adapter.canonical_events()
        self.assertEqual([e["typeName"] for e in canonical], ["touch", "goal"])
        self.assertEqual([e["sequence"] for e in canonical], [1, 2])
        self.assertTrue(any(e["typeName"] == "shot" for e in self.adapter.events))

    def test_deflected_scoring_shot_counts_once_without_assigning_scorer(self):
        self.adapter.consume(touch([1, 12], 8, 100), 0.1)
        deflection = touch([0, 1], 9, 200)
        deflection["touch_type"] = 2
        self.adapter.consume(deflection, 0.2)
        goal = frame(230, score=[0, 1])
        goal["last_touch"] = [0, 1]
        goal["in_play"] = False
        self.adapter.consume(goal, 0.23)
        canonical = self.adapter.canonical_events()
        self.assertEqual([e["typeName"] for e in canonical], ["touch", "touch", "goal"])
        self.assertIsNone(canonical[-1]["playerId"])
        self.assertEqual(canonical[-1]["teamId"], "manutd")
        self.assertIn(
            {"type": "sourceShotEventId", "value": "grf-che-utd-2"},
            canonical[-1]["qualifiers"],
        )

    def test_intentional_control_ends_shot_association(self):
        self.adapter.consume(touch([1, 12], 8, 100), 0.1)
        self.adapter.consume(touch([0, 1], 2, 200), 0.2)
        goal = frame(230, score=[0, 1])
        goal["last_touch"] = [0, 1]
        self.adapter.consume(goal, 0.23)
        self.assertEqual(
            len(
                [e for e in self.adapter.canonical_events() if e["typeName"] == "shot"]
            ),
            1,
        )
        self.assertNotIn(
            "sourceShotEventId",
            [q["type"] for q in self.adapter.events[-1]["qualifiers"]],
        )

    def test_stoppage_ends_shot_association(self):
        self.adapter.consume(touch([1, 12], 8, 100), 0.1)
        stopped = frame(200)
        stopped["in_play"] = False
        self.adapter.consume(stopped, 0.2)
        goal = frame(230, score=[0, 1])
        goal["last_touch"] = [1, 12]
        self.adapter.consume(goal, 0.23)
        self.assertEqual(
            len(
                [e for e in self.adapter.canonical_events() if e["typeName"] == "shot"]
            ),
            1,
        )

    def test_deflection_does_not_complete_pass(self):
        self.adapter.consume(touch([0, 1]), 0.1)
        row = touch([1, 12], 9, 200)
        row["touch_type"] = 2
        self.adapter.consume(row, 0.2)
        self.assertTrue(self.adapter.pending_pass)
        self.adapter.finish_pass(frame(300), 0.3)
        result = [e for e in self.adapter.events if e["typeName"] == "pass"][0]
        self.assertIsNone(result["outcome"])


if __name__ == "__main__":
    unittest.main()
