"""Small integrity check for the rendered demo shared by ETL and narrative fixtures."""

import json
from pathlib import Path
import unittest


class RenderedRecordingTests(unittest.TestCase):
    def test_clock_score_and_supported_measurements(self):
        path = (
            Path(__file__).resolve().parents[1] / "recordings/chelsea-united-grf.json"
        )
        recording = json.loads(path.read_text())
        events = recording["events"]
        self.assertEqual(recording["playback"]["duration_seconds"], 720)
        self.assertEqual(recording["playback"]["halftime_seconds"], 360)
        self.assertEqual(
            [e["sequence"] for e in events], list(range(1, len(events) + 1))
        )
        self.assertEqual(len({e["eventId"] for e in events}), len(events))
        times = [e["videoSeconds"] for e in events]
        self.assertEqual(times, sorted(times))
        self.assertGreaterEqual(times[0], 0)
        self.assertLessEqual(times[-1], 720)
        self.assertEqual({e["periodId"] for e in events}, {1, 2})
        goals = [e for e in events if e["typeName"] == "goal"]
        self.assertEqual([e["teamId"] for e in goals], ["manutd"] * 4)
        event_ids = {e["eventId"] for e in events}
        linked_shots = {
            q["value"]
            for e in goals
            for q in e["qualifiers"]
            if q["type"] == "sourceShotEventId"
        }
        self.assertTrue(linked_shots.isdisjoint(event_ids))
        self.assertFalse(recording["capabilities"]["shot_outcomes"])
        self.assertFalse(recording["capabilities"]["body_parts"])
        self.assertEqual(recording["capabilities"]["distance_event_types"], ["pass"])
        self.assertEqual(len(events), 1376)
        self.assertEqual(sum(e["typeName"] in ("shot", "goal") for e in events), 17)
        self.assertIn("card", recording["capabilities"]["supported_event_types"])
        from collections import Counter
        counts = Counter(e["typeName"] for e in events)
        self.assertEqual({kind: counts[kind] for kind in ("kick_off", "corner", "throw_in", "free_kick", "offside", "foul", "foul_won")},
                         {"kick_off": 6, "corner": 1, "throw_in": 3, "free_kick": 18, "offside": 17, "foul": 1, "foul_won": 1})
        self.assertEqual(recording["capabilities"]["body_part_event_types"], ["pass", "shot"])
        headed_passes = [e for e in events if e["typeName"] == "pass" and
                         {q["type"]: q["value"] for q in e["qualifiers"]}.get("bodyPart") == "head"]
        self.assertEqual(len(headed_passes), 2)
        self.assertFalse(any(e["typeName"] == "shot" and (e["timeMin"], e["timeSec"]) in ((57, 51), (59, 33)) for e in events))
        samples = recording["possession_samples"]
        self.assertTrue(
            all(
                0 <= s["video_seconds"] <= 720 and 0 < s["duration_seconds"] <= 1.1
                for s in samples
            )
        )
        self.assertLess(sum(s["duration_seconds"] for s in samples), 720)
        self.assertEqual(len(recording["players"]), 22)


if __name__ == "__main__":
    unittest.main()
