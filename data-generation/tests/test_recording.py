"""Integrity of the shipped rendered match shared by ETL, the backend and narrative fixtures."""

from collections import Counter
import json
from pathlib import Path
import unittest

RECORDINGS = Path(__file__).resolve().parents[1] / "recordings"


class RenderedRecordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recording = json.loads((RECORDINGS / "riverton-forgeham-grf.json").read_text())
        cls.events = cls.recording["events"]

    def test_real_time_broadcast_clock_and_delivery_order(self):
        events, playback = self.events, self.recording["playback"]
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(len({e["eventId"] for e in events}), len(events))
        times = [e["videoSeconds"] for e in events]
        self.assertEqual(times, sorted(times))
        self.assertLessEqual(times[-1], playback["duration_seconds"])
        clock = [(e["periodId"], e["timeMin"] * 60 + e["timeSec"]) for e in events]
        self.assertEqual(clock, sorted(clock))
        bounds = [(e["periodId"], e["timeMin"], e["timeSec"]) for e in events
                  if e["typeName"] in ("period_start", "period_end")]
        self.assertEqual(bounds, [(1, 0, 0), (1, 46, 18), (2, 45, 0), (2, 91, 6)])

    def test_shipped_match_facts(self):
        counts = Counter(e["typeName"] for e in self.events)
        self.assertEqual(len(self.events), 11133)
        self.assertEqual(self.recording["provenance"]["score"], [1, 1])
        goals = [(e["playerId"], e["timeMin"], e["timeSec"]) for e in self.events if e["typeName"] == "goal"]
        self.assertEqual(goals, [("forgeham-9", 9, 35), ("riverton-9", 71, 16)])
        self.assertEqual({kind: counts[kind] for kind in ("shot", "save", "corner", "card", "offside", "foul")},
                         {"shot": 12, "save": 4, "corner": 5, "card": 0, "offside": 5, "foul": 30})
        self.assertEqual(self.recording["provenance"]["stall_nudge_seconds"], [1700.36, 2251.0, 2716.64, 3225.92, 3792.08])
        self.assertEqual(len(self.recording["players"]), 22)

    def test_capabilities_match_what_the_events_carry(self):
        capabilities = self.recording["capabilities"]
        supported = set(capabilities["supported_event_types"])
        self.assertTrue(set(Counter(e["typeName"] for e in self.events)) <= supported)
        self.assertEqual((capabilities["coordinates"], capabilities["clock"]), ("opta_0_100", "broadcast_with_stoppage"))
        self.assertTrue(all(-2 <= e["x"] <= 102 and -2 <= e["y"] <= 102 for e in self.events if e["x"] is not None))
        self.assertTrue(capabilities["shot_outcomes"])

    def test_possession_samples_stay_on_the_video_timeline(self):
        samples = self.recording["possession_samples"]
        duration = self.recording["playback"]["duration_seconds"]
        self.assertTrue(all(0 <= s["video_seconds"] <= duration and 0 < s["duration_seconds"] <= 1.1 for s in samples))
        self.assertLess(sum(s["duration_seconds"] for s in samples), duration)

    def test_f24_feed_is_the_same_match(self):
        feed = json.loads((RECORDINGS / "riverton-forgeham-grf.opta-f24.json").read_text())
        rows = feed["events"]
        self.assertTrue(feed["synthetic"])
        self.assertEqual(sum(r["type_id"] == 16 for r in rows), 2)
        self.assertTrue(all(0 <= r["x"] <= 100 and 0 <= r["y"] <= 100 for r in rows))
        ids = {r["source_event_id"] for r in rows if "source_event_id" in r}
        self.assertTrue(ids <= {e["eventId"] for e in self.events})


if __name__ == "__main__":
    unittest.main()
