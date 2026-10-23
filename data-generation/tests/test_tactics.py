"""Scripted team tactics: the policy's phase rules, the shipped scripts and the engine patch.

The patch test needs the ignored local clone of google-research/football (skipped without it).
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from grf_demo import prepare_realism, prepare_tactics, tactics
from grf_demo.roster import FIXTURES

CLONE = Path(__file__).resolve().parents[2] / ".local/gfootball-source"
PINNED = "3d9e754720a95621bba6475c4d3b0d56fe919014"
SCRIPT = {
    "styles": {"home": {"press": 0.7}, "away": {"line": -0.1}},
    "phases": [
        {"label": "home spell", "team": "home", "from": 10, "to": 20, "set": {"line": 0.3}, "opponent": {"line": -0.25}},
        {"label": "away tire", "team": "away", "from": 70, "to": 80, "ramp": True, "set": {"energy": 0.5}},
        {"label": "home protect", "team": "home", "from": 60, "when": "leading", "set": {"line": -0.2}},
    ],
}


def at(minute, score=(0, 0)):
    return tactics.evaluate(SCRIPT, ["home", "away"], minute, list(score))


class PolicyTests(unittest.TestCase):
    def test_styles_fill_unset_knobs_with_upstream_defaults(self):
        (home, labels), (away, _) = at(0)
        self.assertEqual(home, {**prepare_tactics.DEFAULTS, "press": 0.7})
        self.assertEqual(away["line"], -0.1)
        self.assertEqual(labels, [])

    def test_phase_steers_its_team_and_the_opponent_inside_its_window_only(self):
        (home, labels), (away, away_labels) = at(10)
        self.assertEqual((home["line"], away["line"]), (0.3, -0.25))
        self.assertEqual(labels, ["home spell"])
        self.assertEqual(away_labels, ["home spell"])
        self.assertEqual(at(20)[0][0]["line"], 0.0)

    def test_ramp_moves_linearly_across_the_window(self):
        self.assertEqual(at(75)[1][0]["energy"], 0.75)

    def test_game_state_phase_follows_the_score_from_its_team_view(self):
        self.assertEqual(at(65, (1, 0))[0][0]["line"], -0.2)
        self.assertEqual(at(65, (0, 1))[0][0]["line"], 0.0)
        self.assertEqual(at(50, (1, 0))[0][0]["line"], 0.0)

    def test_policy_sets_only_changed_knobs_and_logs_phase_changes(self):
        calls = []
        policy = tactics.Policy(SCRIPT, ["home", "away"], lambda *args: calls.append(args) or True)
        policy.apply(0, 0, [0, 0])
        self.assertEqual(len(calls), 2 * len(prepare_tactics.KNOBS))
        calls.clear()
        policy.apply(1, 1 / 60, [0, 0])
        self.assertEqual(calls, [])
        policy.apply(600, 10, [0, 0])
        self.assertEqual(sorted(calls), [(0, "line", 0.3), (1, "line", -0.25)])
        self.assertEqual([c["phases"] for c in policy.changes[-2:]], [["home spell"], ["home spell"]])

    def test_policy_refuses_an_engine_without_the_knobs(self):
        with self.assertRaises(ValueError):
            tactics.Policy(SCRIPT, ["home", "away"], lambda *args: False).apply(0, 0, [0, 0])

    def test_every_fixture_has_a_valid_script_for_its_teams(self):
        for name, fixture in FIXTURES.items():
            script = tactics.load(name)
            self.assertEqual(set(script["styles"]), {team["id"] for team in fixture["teams"]})
            for phase in script["phases"]:
                values = [*phase["set"].values(), *phase.get("opponent", {}).values()]
                self.assertTrue(all(-1 <= value <= 1 for value in values), phase["label"])


@unittest.skipUnless((CLONE / ".git").exists(), "No local pinned GRF clone")
class TacticsPatchTests(unittest.TestCase):
    def test_pinned_source_gains_the_knobs_after_realism_and_reapplying_changes_nothing(self):
        files = ["ai.cpp", "src/onthepitch/teamAIcontroller.cpp", "src/onthepitch/player/controller/elizacontroller.cpp",
                 "src/onthepitch/grf_tactics.hpp"]
        with tempfile.TemporaryDirectory() as directory:
            archive = subprocess.run(["git", "-C", str(CLONE), "archive", PINNED, "third_party/gfootball_engine"],
                                     check=True, capture_output=True).stdout
            subprocess.run(["tar", "-x", "-C", directory], input=archive, check=True)
            engine = Path(directory) / "third_party/gfootball_engine"
            prepare_realism.prepare(Path(directory))
            prepare_tactics.prepare(Path(directory))
            patched = {name: (engine / name).read_text() for name in files}
            self.assertIn('def("set_tactic", &GrfSetTactic);', patched["ai.cpp"])
            for knob in ("kGrfPress", "kGrfLine", "kGrfFlank", "kGrfDirect", "kGrfEnergy"):
                self.assertIn(knob, patched["src/onthepitch/teamAIcontroller.cpp"] +
                              patched["src/onthepitch/player/controller/elizacontroller.cpp"])
            prepare_tactics.prepare(Path(directory))
            self.assertEqual({name: (engine / name).read_text() for name in files}, patched)


if __name__ == "__main__":
    unittest.main()
