"""Fixture rosters: real-name lineups, distinct kits and exports derived from the recording."""

import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grf_demo.opta import export
from grf_demo.opta_stream import ma1
from grf_demo.roster import FIXTURES, fixture_for, players


def recording(name):
    fixture = FIXTURES[name]
    return {"match_id": fixture["match_id"], "events": [],
            "teams": [{"id": t["id"], "name": t["name"]} for t in fixture["teams"]]}


class FixtureTests(unittest.TestCase):
    def test_lineups_and_numbers(self):
        for name, fixture in FIXTURES.items():
            with self.subTest(name):
                for names, numbers in zip(fixture["names"], fixture["numbers"]):
                    self.assertEqual((len(names), len(numbers)), (11, 11))
                    self.assertEqual(len(set(numbers)), 11)
                    self.assertTrue(all(1 <= n <= 99 for n in numbers))
                self.assertEqual(len({t["code"] for t in fixture["teams"]}), 2)

    def test_identities_are_unique_across_fixtures(self):
        teams = [t["id"] for f in FIXTURES.values() for t in f["teams"]]
        self.assertEqual(len(teams), len(set(teams)))
        for key in ("match_id", "event_prefix"):
            self.assertEqual(len({f[key] for f in FIXTURES.values()}), len(FIXTURES))

    def test_exports_follow_the_recording_not_the_environment(self):
        for name in FIXTURES:
            with self.subTest(name):
                document = export(recording(name))
                fixture = FIXTURES[name]
                self.assertIs(fixture_for(recording(name)), fixture)
                self.assertEqual(document["game"]["home_team_id"], fixture["teams"][0]["id"])
                self.assertEqual([p["name"] for p in document["game"]["players"]][:11], list(fixture["names"][0]))
                self.assertEqual([r["team_id"] for r in document["events"]], [t["id"] for t in fixture["teams"]])
                header = ma1(recording(name), document, "0" * 64)
                self.assertTrue(header["synthetic"])
                self.assertEqual(header["matchId"], fixture["match_id"])
                self.assertEqual(header["contestant"][1]["name"], fixture["teams"][1]["name"])
                self.assertEqual(len(players(fixture)), 22)

    @unittest.skipUnless(importlib.util.find_spec("cv2"), "kit recolouring requires OpenCV")
    def test_kits_are_distinct_within_each_fixture(self):
        import cv2
        import numpy as np
        from grf_demo.prepare_cosmetics import recolour

        # Home recolours the bright yellow texture, away the dark navy one (BGR shirt pixels).
        sources = [np.array([[[60, 235, 240]]], np.uint8), np.array([[[80, 10, 2]]], np.uint8)]
        for name, fixture in FIXTURES.items():
            with self.subTest(name):
                home, away = (cv2.cvtColor(recolour(s, t["kit"]), cv2.COLOR_BGR2LAB)[0, 0].astype(float)
                              for s, t in zip(sources, fixture["teams"]))
                self.assertGreater(np.linalg.norm(home - away), 60)  # CIELAB (8-bit) distance.


if __name__ == "__main__":
    unittest.main()
