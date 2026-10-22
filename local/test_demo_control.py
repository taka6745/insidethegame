"""Demo control against a fake feed and owners: one demo, finished runs purged everywhere, cancel."""
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

import demo_control


class DemoControlTests(unittest.TestCase):
    def setUp(self):
        self.runs, self.calls, self.down, self.listed = [], [], set(), []
        self.refuse_restore, self.resume_seq, self.refuse_status = set(), 7, 409
        self.gate = threading.Event()
        self.gate.set()
        self.settings = {"fixtures": ["b", "a", "c"], "main_fixture": "b", "stagger_seconds": 120, "start_points": [{"id": "kickoff", "label": "Kick-off", "period": 1, "minute": 0, "seed": None},
                                          {"id": "20", "label": "20′", "period": 1, "minute": 20, "seed": None}]}

        def handler(request):
            path, body = request.url.path, json.loads(request.content or b"null")
            self.calls.append((request.url.host, path, body))
            if path == "/health":
                return httpx.Response(200 if request.url.host not in self.down else 503, json={})
            if path == "/product/matches":
                return httpx.Response(200, json=[{"match_id": m} for m in self.listed])
            if path == "/runs":
                return httpx.Response(200, json=self.runs)
            if path == "/demo":
                return httpx.Response(200, json=self.settings)
            if path == "/demo/start":
                if any(r["status"] != "finished" for r in self.runs):
                    return httpx.Response(200, json={"started": False, "runs": self.runs})
                point = next(p for p in self.settings["start_points"] if p["id"] == (body or {}).get("point", "kickoff"))
                self.runs = [{"match_id": f"m{i}", "run_id": f"r{i}", "fixture": f, "status": "scheduled",
                              "awaiting_restore": bool(point["seed"]), "seq": self.resume_seq if point["seed"] else 0}
                             for i, f in enumerate(["a", "b", "c"])]
                return httpx.Response(201, json={"started": True, "point": point, "runs": self.runs})
            if path.endswith("/release"):
                run = next(r for r in self.runs if r["match_id"] == path.split("/")[2])
                run.update(awaiting_restore=False, after=body["after_seconds"])
                return httpx.Response(200, json=run)
            if path == "/admin/matches/restore":
                if request.url.host in self.refuse_restore:
                    return httpx.Response(self.refuse_status, json={"detail": "refused"})
                return httpx.Response(200, json={"match_id": body["match_id"], "restored": {}})
            if path == "/admin/matches/purge":
                if request.url.host == "feed":
                    self.gate.wait(5)
                    self.runs = [] if body.get("all") else [r for r in self.runs if r["match_id"] != body["match_id"]]
                return httpx.Response(200, json={"match_ids": [body.get("match_id")], "purged": {}})
            return httpx.Response(404, json={"detail": "nope"})

        self.client = TestClient(demo_control.app(httpx.Client(transport=httpx.MockTransport(handler))))

    def purged(self):
        return [(host, body.get("match_id", "all")) for host, path, body in self.calls if path == "/admin/matches/purge"]

    def test_start_purges_finished_runs_from_the_other_owners_then_starts_once(self):
        self.runs = [{"match_id": "old", "status": "finished"}]
        first = self.client.post("/start").json()
        self.assertTrue(first["started"])
        self.assertEqual(self.purged(), [("etl-stream", "old"), ("narrative-live", "old"), ("backend", "old")])
        self.assertFalse(self.client.post("/start").json()["started"])
        self.assertTrue(self.client.get("/state").json()["live"])

    def test_cancel_purges_every_run_from_every_owner_feed_first(self):
        self.client.post("/start")
        self.runs[0]["status"] = "finished"  # Staggered: the first can end before the others.
        self.assertEqual(self.client.post("/cancel").json()["cancelled"], ["m0", "m1", "m2"])
        self.assertEqual(self.purged(), [("feed", "all"), ("etl-stream", "all"), ("narrative-live", "all"),
                                         ("backend", "all")])

    def test_cancel_with_nothing_on_purges_nothing(self):
        self.assertEqual(self.client.post("/cancel").json()["cancelled"], [])
        self.assertEqual(self.purged(), [])

    def test_a_start_during_a_cancel_waits_and_starts_a_full_demo(self):
        self.client.post("/start")
        self.gate.clear()  # The feed's purge is slow.
        with ThreadPoolExecutor(2) as pool:
            cancelling = pool.submit(self.client.post, "/cancel")
            time.sleep(0.1)
            starting = pool.submit(self.client.post, "/start")
            time.sleep(0.1)
            self.assertFalse(starting.done())
            self.gate.set()
            cancelling.result()
            result = starting.result().json()
        self.assertTrue(result["started"])
        self.assertEqual(len(result["runs"]), 3)

    def seed(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        demo_control.SEED_ROOT, self.settings["start_points"][1]["seed"] = root, "seed-1"
        fixtures = {f: {"source_match_id": f"rec-{f}", "source_run_id": f"run-rec-{f}", "seq": 7,
                        "video_seconds": 1200.0} for f in "abc"}
        (root / "seed-1").mkdir()
        (root / "seed-1" / "manifest.json").write_text(json.dumps({
            "format": demo_control.SEED_FORMAT, "seed_id": "seed-1", "fixtures": fixtures,
            "schemas": {owner: f"{owner}-v1" for owner in demo_control.SEED_OWNERS}}))
        for owner in demo_control.SEED_OWNERS:
            (root / "seed-1" / owner).mkdir()
            for f in "abc":
                part = {"etl": {"matches": [{"matchId": f"rec-{f}", "payload": json.dumps({"matchId": f"rec-{f}",
                                                                                            "timeStamp": "2026-01-01T00:00:00Z"})}]},
                        "engine": {"checkpoints": [{"id": f"rec-{f}", "matchId": f"rec-{f}"}]},
                        "backend": {"received_matches": [{"match_id": f"rec-{f}", "run_id": f"run-rec-{f}",
                                                          "fixture": f}]}}[owner]
                (root / "seed-1" / owner / f"{f}.json").write_text(json.dumps(part))
        return root / "seed-1" / "manifest.json"

    def test_a_seeded_start_restores_every_owner_under_the_new_ids_then_releases_staggered(self):
        self.seed()
        self.settings["stagger_seconds"] = 120
        result = self.client.post("/start", json={"point": "20"}).json()
        self.assertEqual(result["live_from"], "20′")
        restores = [(host, body) for host, path, body in self.calls if path == "/admin/matches/restore"]
        self.assertEqual([h for h, _ in restores[:3]], ["etl-stream", "narrative-live", "backend"])  # ETL first
        etl, engine, backend = (b for _, b in restores[:3])
        # the main game ("b", m1) is restored and released first
        self.assertEqual((etl["match_id"], etl["max_seq"], engine["max_seq"], backend["max_seq"]), ("m1", 7, 7, 7))
        ma1 = json.loads(etl["tables"]["matches"][0]["payload"])
        self.assertEqual(ma1["matchId"], "m1")
        self.assertNotEqual(ma1["timeStamp"], "2026-01-01T00:00:00Z")  # sent now: later than any purge cut-off
        self.assertEqual(engine["containers"]["checkpoints"][0]["matchId"], "m1")
        self.assertEqual(backend["tables"]["received_matches"][0]["run_id"], "r1")
        self.assertEqual({b["schema"] for _, b in restores[:3]}, {"etl-v1", "engine-v1", "backend-v1"})
        self.assertNotIn("rec-", json.dumps([b for _, b in restores]))
        self.assertEqual([r["after"] for r in self.runs], [125, 5, 245])  # a, b (main: furthest along), c

    def test_a_seed_of_another_format_is_refused_before_any_run_starts(self):
        manifest = self.seed()
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), "format": 1}))
        response = self.client.post("/start", json={"point": "20"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("recording again", response.json()["detail"])
        self.assertFalse([c for c in self.calls if c[1] in ("/demo/start", "/admin/matches/restore")])

    def test_an_owner_refusing_the_seed_schema_or_a_seq_mismatch_is_a_409_and_purges_the_runs(self):
        self.seed()
        self.refuse_restore = {"narrative-live"}
        self.assertEqual(self.client.post("/start", json={"point": "20"}).status_code, 409)
        self.assertEqual({m for _, m in self.purged()}, {"m0", "m1", "m2"})
        self.runs, self.refuse_restore, self.resume_seq = [], set(), 8  # the feed resumes after another seq
        self.assertEqual(self.client.post("/start", json={"point": "20"}).status_code, 409)
        self.assertFalse([c for c in self.calls if c[1].endswith("/release")])

    def test_a_recording_in_progress_is_no_demo_and_blocks_a_start(self):
        self.runs = [{"match_id": "rec-a", "fixture": "a", "status": "live", "hold_seconds": 1200.0}]
        self.assertFalse(self.client.get("/state").json()["live"])
        self.assertEqual(self.client.post("/start").status_code, 409)
        self.assertFalse(self.purged())  # the recording is untouched

    def test_a_failed_restore_purges_the_waiting_runs_everywhere(self):
        self.seed()
        self.refuse_restore = {"backend"}
        self.refuse_status = 500
        self.assertEqual(self.client.post("/start", json={"point": "20"}).status_code, 503)
        self.assertEqual({m for _, m in self.purged()}, {"m0", "m1", "m2"})
        self.assertFalse([c for c in self.calls if c[1].endswith("/release")])

    def test_status_reports_each_stage_from_real_checks(self):
        self.down = {"narrative-live"}
        self.client.post("/start")
        stages = {s["id"]: s["ready"] for s in self.client.get("/status").json()["stages"]}
        self.assertEqual(stages, {"feed": True, "event-hubs": False, "etl": True, "service-bus": False,
                                  "engine": False, "backend": True, "viewer": False})
        self.down, self.listed = set(), ["m0"]
        self.runs[0]["position"] = 1  # The first MA1 accepted by the hub; the staggered ones are not due yet.
        self.assertTrue(all(s["ready"] for s in self.client.get("/status").json()["stages"]))
        self.runs[1]["position"] = 1  # Sent but not yet listed by the backend.
        stages = {s["id"]: s["ready"] for s in self.client.get("/status").json()["stages"]}
        self.assertFalse(stages["viewer"])

    def test_a_held_run_has_settled_only_when_every_owner_caught_up(self):
        events = [{"seq": 1, "periodId": 1, "matchTimeSeconds": 1130}, {"seq": 2, "periodId": 1, "matchTimeSeconds": 1199}]
        parts = {"etl": {"matchProgress": [{"seq": 2}], "canonicalEvents": events},
                 "engine": {"checkpoints": [{"closedThrough": "1-019", "lastSummarised": "1-019", "pending": []}],
                            "narratives": [{}]},
                 "backend": {"received_events": [{}, {}], "engine_narratives": [{}]}}
        self.assertTrue(demo_control.settled(parts, {"seq": 2}))
        self.assertFalse(demo_control.settled(parts, {"seq": 3}))  # the ETL is behind the feed
        parts["engine"]["checkpoints"][0]["pending"] = [{"ref": "x"}]
        self.assertFalse(demo_control.settled(parts, {"seq": 2}))  # the engine still has work
        parts["engine"]["checkpoints"][0]["pending"] = []
        parts["backend"]["engine_narratives"] = []
        self.assertFalse(demo_control.settled(parts, {"seq": 2}))  # a narrative is still on the bus

    def test_state_names_the_main_game_to_open_by_default(self):
        self.assertEqual([self.client.get("/state").json()[k] for k in ("main_fixture", "main_match_id")], ["b", None])
        self.client.post("/start")
        self.assertEqual(self.client.get("/state").json()["main_match_id"], "m1")  # fixture "b"
        del self.settings["main_fixture"]  # a feed without the setting: its first fixture
        self.assertEqual(self.client.get("/state").json()["main_fixture"], "b")

    def test_state_marks_points_without_a_seed_not_ready(self):
        self.assertEqual([p["ready"] for p in self.client.get("/state").json()["points"]], [True, False])

    def test_state_marks_a_stale_seed_not_ready(self):
        manifest = self.seed()
        self.assertEqual([p["ready"] for p in self.client.get("/state").json()["points"]], [True, True])
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), "format": 1}))
        self.assertEqual([p["ready"] for p in self.client.get("/state").json()["points"]], [True, False])


if __name__ == "__main__":
    unittest.main()
