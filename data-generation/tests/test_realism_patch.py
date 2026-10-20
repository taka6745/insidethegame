"""The realism patch applies to the pinned upstream engine (independently of the telemetry
instrumentation) and is idempotent.

Needs the ignored local clone of google-research/football (skipped without it).
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grf_demo import prepare_realism
from grf_demo.scenario import REALISM

CLONE = Path(__file__).resolve().parents[2] / ".local/gfootball-source"
PINNED = "3d9e754720a95621bba6475c4d3b0d56fe919014"
FILES = ["data/playerdata.cpp", "onthepitch/player/controller/elizacontroller.cpp",
         "onthepitch/AIsupport/AIfunctions.cpp", "onthepitch/player/humanoid/humanoid.cpp",
         "onthepitch/player/controller/strategies/offtheball/goalie_default.cpp", "onthepitch/referee.cpp"]


@unittest.skipUnless((CLONE / ".git").exists(), "No local pinned GRF clone")
class RealismPatchTests(unittest.TestCase):
    def test_pinned_source_gains_every_knob_once_and_reapplying_changes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = subprocess.run(["git", "-C", str(CLONE), "archive", PINNED, "third_party/gfootball_engine"],
                                     check=True, capture_output=True).stdout
            subprocess.run(["tar", "-x", "-C", directory], input=archive, check=True)
            root = Path(directory) / "third_party/gfootball_engine/src"
            pristine = {name: (root / name).read_text() for name in FILES}
            prepare_realism.prepare(Path(directory))
            patched = {name: (root / name).read_text() for name in FILES}
            self.assertTrue(all(patched[name] != pristine[name] for name in FILES))
            text = "".join(patched.values())
            for knob in [*REALISM, "GRF_FOUL_BIAS"]:
                self.assertIn(f'"{knob}"', text)
                self.assertNotIn(f'"{knob}"', "".join(pristine.values()))
            prepare_realism.prepare(Path(directory))
            self.assertEqual({name: (root / name).read_text() for name in FILES}, patched)


if __name__ == "__main__":
    unittest.main()
