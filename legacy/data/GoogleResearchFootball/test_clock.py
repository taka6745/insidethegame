"""Prove clock speed and the halftime transition in the patched native engine."""

import itertools
import json
import unittest

try:
    import gfootball_engine

    PATCHED = hasattr(gfootball_engine.GameConfig.make(), "match_duration")
except ImportError:
    PATCHED = False


@unittest.skipUnless(PATCHED, "Requires the native render patch")
class ClockTests(unittest.TestCase):
    def test_one_to_one_clock_and_halftime(self):
        from gfootball.env import football_env_core
        from gfootball.env.football_action_set import action_builtin_ai
        from render import make_match
        from run import engine

        # GRF pools engines without rebuilding their startup clock configuration.
        # Isolate this test from any earlier default-clock environment.
        football_env_core._unused_engines.clear()
        env = make_match(42, 25, 1280, False)
        try:
            native = engine(env)
            self.assertAlmostEqual(native.game_config.match_duration, 4.75)
            self.assertEqual(native.config.second_half, 1500)
            native.config.second_half = (
                1  # Exercise the same referee boundary at 1.8 s.
            )
            native.telemetry_enabled = True
            for left in (True, False):
                native.perform_action(action_builtin_ai._backend_action, left, 0)
            frames = []
            for _ in range(125):
                native.step()
                frames.extend(
                    r
                    for s in native.drain_telemetry()
                    if (r := json.loads(s))["kind"] == "frame"
                )
            self.assertEqual({r["phase"] for r in frames}, {1, 2})
            advancing = [
                b["match_ms"] - a["match_ms"]
                for a, b in itertools.pairwise(frames)
                if b["match_ms"] != a["match_ms"]
            ]
            self.assertTrue(advancing)
            self.assertEqual(set(advancing), {10})
            half = next(r for r in frames if r["phase"] == 2)
            self.assertGreaterEqual(half["match_ms"], 1800)
            self.assertLess(half["match_ms"], 1900)
        finally:
            env.close()
            football_env_core._unused_engines.clear()


if __name__ == "__main__":
    unittest.main()
