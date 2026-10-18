"""Optional integration test: run inside the built simulator image."""

import json
import unittest

try:
    import gfootball
except ImportError:
    gfootball = None

from run import engine, make_env


@unittest.skipIf(gfootball is None, "Requires the GRF Docker image")
class NativeCoordinates(unittest.TestCase):
    def test_player_coordinates_and_velocities_match_public_api(self):
        env = make_env(42)
        try:
            native = engine(env)
            native.telemetry_enabled = True
            for _ in range(30):
                obs, _, _, _ = env.step([19, 19])
                frames = [json.loads(r) for r in native.drain_telemetry()]
                last = next(r for r in reversed(frames) if r["kind"] == "frame")
                for p in last["players"]:
                    side = "left" if p["team"] == 0 else "right"
                    position = obs[0][side + "_team"][p["index"]]
                    direction = obs[0][side + "_team_direction"][p["index"]]
                    for axis, scale in enumerate((54.4, -83.6)):
                        self.assertAlmostEqual(
                            float(position[axis]) * scale,
                            p["position_m"][axis],
                            places=4,
                        )
                        self.assertAlmostEqual(
                            float(direction[axis]) * scale * 10,
                            p["velocity_mps"][axis],
                            places=4,
                        )
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
