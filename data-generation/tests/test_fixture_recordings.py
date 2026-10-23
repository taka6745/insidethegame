"""Shipped Redcastle Town–Port Albion and Skybridge City–Whitmore recordings: integrity, facts and exports."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "etl"))
from grf_demo.opta import export
from grf_demo.opta_stream import stream
from reference import pipeline

RECORDINGS = ROOT / "data-generation" / "recordings"

FACTS = {
    "redcastle-portalbion": {
        "seed": 31, "score": [1, 0], "events": 10902, "f24Rows": 2428, "nudges": [217.12],
        "bounds": [(1, 0, 0), (1, 46, 18), (2, 45, 0), (2, 91, 20)],
        "goals": [("redcastle-2", 46, 9)],
        "cards": [("redcastle-9", "yellow"), ("portalbion-9", "yellow")],
        "counts": {"shot": 17, "save": 7, "corner": 3, "card": 2, "offside": 16, "foul": 26},
        "reference": {"shots": (10, 8), "shotsOnTarget": (5, 2), "corners": (2, 1), "yellowCards": (1, 1),
                      "redCards": (0, 0)},
    },
    "skybridge-whitmore": {
        "seed": 43, "score": [1, 1], "events": 11295, "f24Rows": 2575, "nudges": [1019.12, 2590.08, 2909.72, 4604.12],
        "bounds": [(1, 0, 0), (1, 46, 47), (2, 45, 0), (2, 91, 19)],
        "goals": [("skybridge-4", 47, 50), ("skybridge-3", 69, 30)],
        "cards": [("skybridge-9", "yellow"), ("whitmore-9", "yellow"), ("whitmore-7", "yellow"),
                  ("whitmore-7", "second_yellow")],
        "counts": {"shot": 9, "save": 4, "corner": 7, "card": 4, "offside": 8, "foul": 33},
        "reference": {"shots": (9, 1), "shotsOnTarget": (4, 0), "corners": (4, 3), "yellowCards": (1, 2),
                      "redCards": (0, 1)},
    },
}


class FixtureRecordingTests(unittest.TestCase):
    def test_recordings(self):
        for fixture, facts in FACTS.items():
            with self.subTest(fixture):
                content = (RECORDINGS / f"{fixture}-grf.json").read_bytes()
                recording = json.loads(content)
                events, provenance = recording["events"], recording["provenance"]
                self.assertTrue(recording["synthetic"])
                self.assertTrue(all(e["synthetic"] for e in events))
                self.assertIn("Google Research Football", provenance["source"])
                self.assertEqual(provenance["tactics"]["script"]["styles"].keys(), {t["id"] for t in recording["teams"]})
                self.assertTrue(provenance["tactics"]["changes"])
                self.assertEqual((recording["match_id"], provenance["fixture"]), (fixture, fixture))
                self.assertEqual((provenance["seed"], provenance["score"]), (facts["seed"], facts["score"]))
                self.assertEqual(provenance["stall_nudge_seconds"], facts["nudges"])
                self.assertEqual(len(recording["players"]), 22)

                self.assertEqual(len(events), facts["events"])
                self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
                self.assertEqual(len({e["eventId"] for e in events}), len(events))
                times = [e["videoSeconds"] for e in events]
                self.assertEqual(times, sorted(times))
                self.assertLessEqual(times[-1], recording["playback"]["duration_seconds"])
                self.assertEqual([(e["periodId"], e["timeMin"], e["timeSec"]) for e in events
                                  if e["typeName"] in ("period_start", "period_end")], facts["bounds"])
                self.assertEqual([(e["playerId"], e["timeMin"], e["timeSec"]) for e in events
                                  if e["typeName"] == "goal"], facts["goals"])
                self.assertEqual([(e["playerId"], e["outcome"]) for e in events if e["typeName"] == "card"],
                                 facts["cards"])
                counts = Counter(e["typeName"] for e in events)
                self.assertEqual({k: counts[k] for k in facts["counts"]}, facts["counts"])
                self.assertTrue(set(counts) <= set(recording["capabilities"]["supported_event_types"]))

                f24 = json.loads((RECORDINGS / f"{fixture}-grf.opta-f24.json").read_text())
                self.assertTrue(f24["synthetic"])
                self.assertEqual(sum(r["type_id"] == 16 for r in f24["events"]), sum(facts["score"]))

                self.assertEqual(json.dumps(export(recording), separators=(",", ":")),
                                 (RECORDINGS / f"{fixture}-grf.opta-f24.json").read_text())
                self.assertEqual(len(f24["events"]), facts["f24Rows"])
                messages = stream(recording, hashlib.sha256(content).hexdigest())
                shipped = (RECORDINGS / f"{fixture}-grf.opta-stream.jsonl").read_text(encoding="utf-8")
                self.assertEqual([json.loads(line) for line in shipped.splitlines()], messages)
                # One MA3 offside pass per canonical offside, credited to the offside player's team.
                self.assertEqual(Counter(m["contestantId"] for m in messages[1:] if m["typeId"] == 2),
                                 Counter(e["teamId"] for e in events if e["typeName"] == "offside"))
                outputs = pipeline.stream_outputs(messages, 60)
                rows = pipeline.stats_as_of(outputs["minuteStats"], outputs["matches"])
                last = max((r["periodId"], r["timeMin"]) for r in rows)
                final = {r["position"]: r for r in rows if (r["periodId"], r["timeMin"]) == last}
                self.assertEqual((final["home"]["goals"], final["away"]["goals"]), tuple(facts["score"]))
                for column, expected in facts["reference"].items():
                    self.assertEqual((final["home"][column], final["away"][column]), expected, column)


if __name__ == "__main__":
    unittest.main()
