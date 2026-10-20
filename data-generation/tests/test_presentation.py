import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grf_demo.prepare_presentation import numbered_kit, prepare, replace_once
from grf_demo.roster import NAMES, SHIRT_NUMBERS


class PresentationPatchTests(unittest.TestCase):
    def test_roster_numbers_match_slots_and_are_unique_per_team(self):
        for names, numbers in zip(NAMES, SHIRT_NUMBERS):
            self.assertEqual(len(names), len(numbers))
            self.assertEqual(len(numbers), len(set(numbers)))
            self.assertTrue(all(1 <= number <= 99 for number in numbers))

    def test_patch_refuses_unexpected_native_source(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "source.cpp"
            path.write_text("unrelated source")
            with self.assertRaises(ValueError):
                replace_once(path, "old code", "new code")
            self.assertEqual(path.read_text(), "unrelated source")

    @unittest.skipUnless(importlib.util.find_spec("cv2"), "GRF presentation requires OpenCV")
    def test_native_patch_and_all_numbered_textures_are_repeatable(self):
        import cv2
        import numpy as np

        with TemporaryDirectory() as folder:
            source = Path(folder)
            engine = source / "third_party/gfootball_engine"
            native = engine / "src/onthepitch"
            native.mkdir(parents=True)
            (native / "match.cpp").write_text("  radar->Show();\n  radar->Put();")
            (native / "team.cpp").write_text("      kit = GetContext().surface_manager.Fetch(kitFilename);")
            (engine / "src/gamedefines.hpp").write_text("Zoom = 0.5f\nHeight = 0.3f")
            textures = engine / "data/media/objects/players/textures"
            textures.mkdir(parents=True)
            kits = engine / "data/databases/default/images_teams/primeradivision"
            kits.mkdir(parents=True)
            image = np.full((1024, 1024, 3), (180, 40, 20), dtype=np.uint8)
            for path in (textures / "goalie_kit.bmp", kits / "fcbarcelona_kit_02.bmp", kits / "realmadrid_kit_02.bmp"):
                cv2.imwrite(str(path), image)

            prepare(source)
            first = {p.name: p.read_bytes() for p in textures.glob("demo_*.bmp")}
            prepare(source)
            self.assertEqual(first, {p.name: p.read_bytes() for p in textures.glob("demo_*.bmp")})
            self.assertEqual(len(first), 22)
            self.assertNotIn("radar->Show()", (native / "match.cpp").read_text())
            self.assertNotIn("radar->Put()", (native / "match.cpp").read_text())
            self.assertIn("demo_team_", (native / "team.cpp").read_text())
            self.assertIn("Zoom = 0.7f", (engine / "src/gamedefines.hpp").read_text())

            numbered = numbered_kit(image, 10)
            np.testing.assert_array_equal(numbered[:, :620], image[:, :620])
            np.testing.assert_array_equal(numbered[420:], image[420:])
            self.assertTrue(np.any(numbered[90:405, 625:910] != image[90:405, 625:910]))
            self.assertNotEqual(first["demo_team_0_player_0.bmp"], first["demo_team_0_player_1.bmp"])


if __name__ == "__main__":
    unittest.main()
