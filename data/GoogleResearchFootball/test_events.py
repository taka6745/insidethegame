"""Pass truth must follow engine contacts, including deflections and unknown endings."""

import unittest

from events import Events


def touch(t, player, fn=4, touch_type=0, x=0):
    return dict(
        kind="touch",
        physics_ms=t,
        match_ms=t * 10,
        player=player,
        function=fn,
        touch_type=touch_type,
        ball_position_m=[x, 0, 0],
        ball_velocity_mps=[10, 0, 0],
        target_player=None,
        forced_target_player=None,
    )


def frame(t, x=0, in_play=True):
    return dict(
        kind="frame",
        physics_ms=t,
        match_ms=t * 10,
        ball_position_m=[x, 0, 0],
        in_play=in_play,
        game_mode=0,
        phase=0,
        score=[0, 0],
        owner=[-1, -1],
        players=[],
    )


class PassTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        self.events = Events(self.rows.append)

    def test_teammate_control_completes_pass_and_tracks_full_path(self):
        e = self.events
        e.consume(frame(0, x=-1))
        e.consume(touch(10, [0, 2], x=0))
        e.consume(frame(20, x=2))
        e.consume(frame(30, x=3))
        e.consume(touch(40, [0, 3], fn=2, x=4))
        p = e.passes[0]
        self.assertTrue(p["completed"])
        self.assertEqual(p["receiver"], [0, 3])
        self.assertEqual(p["flight_path_m"], 4)
        self.assertEqual(p["displacement_m"], 4)
        self.assertEqual(p["duration_s"], 0.03)
        self.assertEqual(p["launch_speed_kmh"], 36)
        self.assertEqual(p["direction_degrees"], 0)

    def test_accidental_touch_does_not_end_pass(self):
        e = self.events
        e.consume(touch(0, [0, 2]))
        e.consume(touch(20, [1, 4], fn=9, touch_type=2, x=1))
        self.assertEqual(len(e.passes), 0)
        e.consume(touch(50, [0, 3], fn=2, x=2))
        self.assertTrue(e.passes[0]["completed"])
        self.assertEqual(
            e.passes[0]["deflections"], [{"player": [1, 4], "physics_ms": 20}]
        )

    def test_interception_and_self_recovery_are_not_completions(self):
        for receiver, outcome in (
            ([1, 3], "opponent_control"),
            ([0, 2], "self_recovery"),
        ):
            e = Events(lambda _: None)
            e.consume(touch(0, [0, 2]))
            e.consume(touch(10, receiver, fn=2))
            self.assertFalse(e.passes[0]["completed"])
            self.assertEqual(e.passes[0]["outcome"], outcome)

    def test_play_stop_closes_pass(self):
        e = self.events
        e.consume(frame(0))
        e.consume(touch(10, [0, 2]))
        e.consume(frame(20, in_play=False))
        self.assertFalse(e.passes[0]["completed"])
        self.assertEqual(e.passes[0]["outcome"], "play_stopped")

    def test_export_cutoff_preserves_unknown_completion(self):
        e = self.events
        e.consume(frame(0))
        e.consume(touch(10, [0, 2]))
        e.consume(frame(20, x=1))
        e.finish()
        self.assertIsNone(e.passes[0]["completed"])
        self.assertEqual(e.passes[0]["outcome"], "unresolved_at_export_end")

    def test_animation_attempt_is_not_an_executed_pass(self):
        e = self.events
        for t, fn in ((0, 1), (10, 4)):
            r = frame(t)
            r["players"] = [
                dict(team=0, id=2, function=fn, has_card=False, active=True)
            ]
            e.consume(r)
        self.assertEqual([r["type"] for r in self.rows], ["action_started"])
        self.assertEqual(e.counts["pass"], 0)


if __name__ == "__main__":
    unittest.main()
