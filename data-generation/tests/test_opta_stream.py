"""MA1/MA3 stream export, checked with the ETL reference rules (etl/reference)."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "etl"))
from grf_demo.opta_stream import SPADL_PASS_FAMILY, body_part_action_types, pos_rows, stream
from reference import pipeline

RECORDINGS = ROOT / "data-generation" / "recordings"


class OptaStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        content = (RECORDINGS / "riverton-forgeham-grf.json").read_bytes()
        cls.recording = json.loads(content)
        cls.messages = stream(cls.recording, hashlib.sha256(content).hexdigest())
        cls.outputs = pipeline.stream_outputs(cls.messages, 60)

    def test_shipped_stream_is_reproducible(self):
        shipped = (RECORDINGS / "riverton-forgeham-grf.opta-stream.jsonl").read_text(encoding="utf-8")
        self.assertEqual([json.loads(line) for line in shipped.splitlines()], self.messages)

    def test_contract_shape(self):
        ma1, *ma3 = self.messages
        self.assertEqual(ma1["feed"], "MA1")
        self.assertEqual([c["position"] for c in ma1["contestant"]], ["home", "away"])
        self.assertEqual([len(c["lineup"]) for c in ma1["contestant"]], [11, 11])
        self.assertTrue(all(m["synthetic"] for m in self.messages))
        self.assertEqual([m["seq"] for m in ma3], list(range(1, len(ma3) + 1)))
        self.assertNotIn(34, {m["typeId"] for m in ma3})
        canonical = {e["eventId"] for e in self.recording["events"]}
        self.assertTrue(all(m["sourceEventId"] in canonical for m in ma3))
        periods = [m for m in ma3 if m["typeId"] in (30, 32)]
        self.assertTrue(all(m["x"] is None and m["y"] is None for m in periods))
        times = [m["timeStamp"] for m in ma3]
        self.assertEqual(times, sorted(times))

    def test_ma1_additions(self):
        ma1 = self.messages[0]
        self.assertEqual((ma1["fixture"], ma1["sourceMatchId"]), ("riverton-forgeham", "product-demo-match"))
        self.assertTrue(ma1["provenance"].startswith("SYNTHETIC"))
        self.assertIn("Google Research Football (Apache-2.0)", ma1["provenance"])
        caps = ma1["capabilities"]
        self.assertTrue(caps["canonicalEvents"] and caps["possessionSamples"])
        self.assertEqual((caps["periods"], caps["restartEvents"], caps["video"]), (2, "taken", False))
        self.assertIn("goal", caps["eventTypes"])
        # Body-part coverage in SPADL action types beside the provider's event types.
        self.assertEqual(caps["bodyPartEventTypes"], ["pass", "shot", "goal"])
        self.assertEqual(caps["bodyPartActionTypes"][:2] + caps["bodyPartActionTypes"][-3:],
                         ["pass", "cross", "shot", "shot_penalty", "shot_freekick"])
        self.assertEqual(body_part_action_types(["pass", "shot"]), list(SPADL_PASS_FAMILY))  # Goals unknown.
        self.assertEqual(set(ma1["branding"]), {"riverton", "forgeham"})
        self.assertTrue(all(b["primaryColour"].startswith("#") for b in ma1["branding"].values()))
        self.assertEqual([(c["code"], c["shortName"]) for c in ma1["contestant"]],
                         [("RVR", "Riverton"), ("FGU", "Forgeham")])
        self.assertEqual([c["knownNames"] for c in ma1["contestant"]], [["the Rovers", "the Blues"], ["United", "the Forgemen"]])

    def test_event_seq_follows_canonical_order(self):
        seqs = {e["eventId"]: i for i, e in enumerate(self.recording["events"], 1)}
        ma3 = self.messages[1:]
        self.assertTrue(all(m["eventSeq"] == seqs[m["sourceEventId"]] for m in ma3))
        self.assertEqual([m["eventSeq"] for m in ma3], sorted(m["eventSeq"] for m in ma3))

    def test_possession_samples(self):
        pos = pos_rows(self.recording)
        events = self.recording["events"]
        self.assertEqual([p["sampleId"] for p in pos], list(range(1, len(pos) + 1)))
        for p in pos:
            # POS goes before canonical events at the same video time.
            if p["eventSeq"]:
                self.assertLess(events[p["eventSeq"] - 1]["videoSeconds"], p["videoSeconds"])
            if p["eventSeq"] < len(events):
                self.assertGreaterEqual(events[p["eventSeq"]]["videoSeconds"], p["videoSeconds"])
        owned = Counter()
        for p in pos:
            owned[p["contestantId"]] += p["durationSeconds"]
        share = round(100 * owned["riverton"] / sum(owned.values()))
        self.assertEqual(share, 64)

    def test_reference_totals(self):
        rows = pipeline.stats_as_of(self.outputs["minuteStats"], self.outputs["matches"])
        last = max((r["periodId"], r["timeMin"]) for r in rows)
        final = {r["position"]: r for r in rows if (r["periodId"], r["timeMin"]) == last}
        pick = lambda column: (final["home"][column], final["away"][column])
        self.assertEqual(pick("goals"), (1, 1))
        self.assertEqual(pick("shots"), (9, 5))
        self.assertEqual(pick("shotsOnTarget"), (3, 2))
        self.assertEqual(pick("corners"), (2, 3))
        self.assertEqual(pick("redCards"), (0, 0))
        self.assertEqual([k["keyType"] for k in self.outputs["keyEvents"]], ["PenaltyAwarded", "Goal", "PenaltyAwarded", "Goal"])

    def test_one_window_per_match_minute(self):
        closed = [n for n in self.outputs["notifications"] if n["messageType"] == "MinuteClosed"]
        self.assertEqual(len(closed), len({(n["periodId"], n["timeMin"]) for n in closed}))
        minutes = {(e["periodId"], e["timeMin"]) for e in self.outputs["rawEvents"]}
        self.assertEqual({(n["periodId"], n["timeMin"]) for n in closed}, minutes)
        kinds = Counter(n["messageType"] for n in self.outputs["notifications"])
        self.assertEqual((kinds["PeriodStarted"], kinds["PeriodEnded"], kinds["KeyEventDetected"]), (2, 2, 4))


if __name__ == "__main__":
    unittest.main()
