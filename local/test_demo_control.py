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
        self.refuse_restore, self.resume_seq, self.refuse_status, self.refuse_purge = set(), 7, 409, set()
        self.gate = threading.Event()
        self.gate.set()
        self.slow_purge, self.owner_gate, self.purging = set(), threading.Event(), threading.Event()
        self.owner_gate.set()
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
            if path == "/demo/skip":
                if not any(r["status"] != "finished" for r in self.runs):
                    return httpx.Response(409, json={"detail": "No demo is playing yet."})
                return httpx.Response(200, json={"skipped_seconds": 600, "target": body, "runs": self.runs})
            if path.endswith("/release"):
                run = next(r for r in self.runs if r["match_id"] == path.split("/")[2])
                run.update(awaiting_restore=False, after=body["after_seconds"])
                return httpx.Response(200, json=run)
            if path == "/admin/matches/restore":
                if request.url.host in self.refuse_restore:
                    return httpx.Response(self.refuse_status, json={"detail": "refused"})
                return httpx.Response(200, json={"match_id": body["match_id"], "restored": {}})
            if path == "/admin/matches/purge":
                if request.url.host in self.refuse_purge:
                    return httpx.Response(500, json={"detail": "down"})
                if body.get("match_id") in self.slow_purge:
                    self.purging.set()
                    self.owner_gate.wait(5)
                if request.url.host == "feed":
                    self.gate.wait(5)
                    self.runs = [] if body.get("all") else [r for r in self.runs if r["match_id"] != body["match_id"]]
                return httpx.Response(200, json={"match_ids": [body.get("match_id")], "purged": {}})
            return httpx.Response(404, json={"detail": "nope"})

        self.now = 0.0  # the sweep's clock
        self.client = TestClient(demo_control.app(httpx.Client(transport=httpx.MockTransport(handler)),
                                                  clock=lambda: self.now))

    def settle(self):
        """Wait for the queued start or cancel to finish; how it ended (start and cancel answer 202 at once)."""
        for _ in range(500):
            state = self.client.get("/state").json()
            if not state["pending"]:
                return state["last"]
            time.sleep(0.01)
        self.fail("the demo job did not finish")

    def purged(self):
        return [(host, body.get("match_id", "all")) for host, path, body in self.calls if path == "/admin/matches/purge"]

    def test_start_purges_finished_runs_from_the_other_owners_then_starts_once(self):
        self.runs = [{"match_id": "old", "status": "finished"}]
        self.assertEqual(self.client.post("/start").status_code, 202)
        self.assertTrue(self.settle()["started"])
        self.assertEqual(sorted(self.purged()), [("backend", "old"), ("etl-stream", "old"), ("narrative-live", "old")])
        self.assertFalse(self.client.post("/start").json()["started"])
        self.assertTrue(self.client.get("/state").json()["live"])

    def test_cancel_purges_every_run_from_every_owner_feed_first(self):
        self.client.post("/start")
        self.settle()
        self.runs[0]["status"] = "finished"  # Staggered: the first can end before the others.
        self.assertEqual(self.client.post("/cancel").status_code, 202)
        self.assertEqual(self.settle()["cancelled"], ["m0", "m1", "m2"])
        purged = self.purged()
        self.assertEqual(purged[0], ("feed", "all"))  # the feed first; the others after it, at once
        self.assertEqual(sorted(purged[1:]), [("backend", "all"), ("etl-stream", "all"), ("narrative-live", "all")])

    def test_a_finished_run_of_a_live_demo_is_never_swept(self):
        self.runs = [{"match_id": "old", "status": "finished"}, {"match_id": "live", "status": "playing"}]
        self.assertEqual(self.client.app.state.sweep_once(), [])
        self.now += demo_control.SWEEP_GRACE_SECONDS * 10  # however long the rest of the demo plays
        self.assertEqual(self.client.app.state.sweep_once(), [])
        self.assertEqual(self.purged(), [])

    def test_finished_runs_are_swept_between_demos_so_a_start_purges_nothing(self):
        self.runs = [{"match_id": "old", "status": "finished"}]
        self.assertEqual(self.client.app.state.sweep_once(), [])  # just finished: still watchable at full time
        self.now += demo_control.SWEEP_GRACE_SECONDS
        self.assertEqual(self.client.app.state.sweep_once(), ["old"])
        self.assertEqual(self.client.app.state.sweep_once(), [])  # once only
        self.runs = [{"match_id": "old", "status": "finished"}]
        self.calls.clear()
        self.client.post("/start")
        self.assertTrue(self.settle()["started"])
        self.assertEqual(self.purged(), [])

    def test_a_cancel_never_waits_on_a_sweeps_purge(self):
        self.runs = [{"match_id": "old", "status": "finished"}]
        self.client.app.state.sweep_once()  # sees it finish
        self.now += demo_control.SWEEP_GRACE_SECONDS
        self.slow_purge.add("old")
        self.owner_gate.clear()  # the sweep's purge of "old" hangs (a slow owner)
        sweep = threading.Thread(target=self.client.app.state.sweep_once)
        sweep.start()
        self.assertTrue(self.purging.wait(5))
        began = time.monotonic()
        self.client.post("/cancel")
        self.settle()
        self.assertLess(time.monotonic() - began, 3)  # not held up by the sweep
        self.owner_gate.set()
        sweep.join(5)

    def test_a_sweep_waits_out_a_start_or_cancel(self):
        self.runs = [{"match_id": "old", "status": "finished"}]
        self.gate.clear()
        self.client.post("/cancel")
        self.assertEqual(self.client.app.state.sweep_once(), [])
        self.gate.set()
        self.settle()

    def test_cancel_with_nothing_on_purges_nothing(self):
        self.assertEqual(self.client.post("/cancel").json()["cancelled"], [])
        self.assertEqual(self.purged(), [])

    def test_a_start_during_a_cancel_waits_and_starts_a_full_demo(self):
        self.client.post("/start")
        self.settle()
        self.gate.clear()  # The feed's purge is slow: both requests still answer at once.
        self.assertEqual(self.client.post("/cancel").status_code, 202)
        self.assertEqual(self.client.post("/start").status_code, 202)
        self.assertEqual(self.client.get("/state").json()["pending"], ["cancel", "start"])
        self.gate.set()
        result = self.settle()
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
        self.client.post("/start", json={"point": "20"})
        self.assertEqual(self.settle()["live_from"], "20′")
        restores = [(host, body) for host, path, body in self.calls if path == "/admin/matches/restore"]
        # The runs restore in parallel; per run the ETL alongside the backend, then the engine.
        main = {h: b for h, b in restores if b["match_id"] == "m1"}  # the main game ("b", m1)
        hosts = [h for h, b in restores if b["match_id"] == "m1"]
        self.assertEqual(sorted(hosts), ["backend", "etl-stream", "narrative-live"])
        self.assertLess(hosts.index("backend"), hosts.index("narrative-live"))
        etl, engine, backend = main["etl-stream"], main["narrative-live"], main["backend"]
        self.assertEqual((etl["max_seq"], engine["max_seq"], backend["max_seq"]), (7, 7, 7))
        ma1 = json.loads(etl["tables"]["matches"][0]["payload"])
        self.assertEqual(ma1["matchId"], "m1")
        self.assertNotEqual(ma1["timeStamp"], "2026-01-01T00:00:00Z")  # sent now: later than any purge cut-off
        self.assertEqual(engine["containers"]["checkpoints"][0]["matchId"], "m1")
        self.assertEqual(backend["tables"]["received_matches"][0]["run_id"], "r1")
        self.assertEqual({b["schema"] for b in main.values()}, {"etl-v1", "engine-v1", "backend-v1"})
        self.assertNotIn("rec-", json.dumps([b for _, b in restores]))
        self.assertEqual([r["after"] for r in self.runs], [125, 5, 245])  # a, b (main: furthest along), c

    def test_the_picker_reads_offered_seeds_into_memory_so_a_start_reads_nothing_from_the_share(self):
        manifest = self.seed()
        self.client.get("/state")
        for _ in range(100):
            if len([p for p in demo_control._seed_texts if p.parents[1] == manifest.parent]) == 9:
                break
            time.sleep(0.01)
        for owner in demo_control.SEED_OWNERS:  # gone from the share: the start uses what the picker read
            __import__("shutil").rmtree(manifest.parent / owner)
        self.client.post("/start", json={"point": "20"})
        self.assertEqual(self.settle()["live_from"], "20′")
        demo_control.preload_seeds(frozenset(), "abc")  # a seed no longer offered is forgotten
        self.assertFalse([p for p in demo_control._seed_texts if p.parents[1] == manifest.parent])

    def test_a_seeded_start_purges_the_previous_demo_alongside_the_restore_and_releases_after_it(self):
        self.seed()
        self.runs = [{"match_id": "old", "status": "finished"}]
        self.client.post("/start", json={"point": "20"})
        self.assertEqual(self.settle()["live_from"], "20′")
        order = [(h, p) for h, p, _ in self.calls if p in ("/admin/matches/purge", "/demo/start") or p.endswith("/release")]
        purges = [i for i, (h, p) in enumerate(order) if p == "/admin/matches/purge"]
        releases = [i for i, (h, p) in enumerate(order) if p.endswith("/release")]
        self.assertEqual(len(purges), 3)
        self.assertLess(max(purges), min(releases))  # viewers never list the old matches beside the new three

    def test_a_seed_of_another_format_is_refused_before_any_run_starts(self):
        manifest = self.seed()
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), "format": 1}))
        response = self.client.post("/start", json={"point": "20"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("isn't available right now", response.json()["detail"])  # the seed error is logged, never shown
        self.assertFalse([c for c in self.calls if c[1] in ("/demo/start", "/admin/matches/restore")])

    def test_an_owner_refusing_the_seed_schema_or_a_seq_mismatch_is_a_409_and_purges_the_runs(self):
        self.seed()
        self.refuse_restore = {"narrative-live"}
        self.client.post("/start", json={"point": "20"})
        self.assertEqual(self.settle()["status"], 409)
        self.assertEqual({m for _, m in self.purged()}, {"m0", "m1", "m2"})
        self.runs, self.refuse_restore, self.resume_seq = [], set(), 8  # the feed resumes after another seq
        self.client.post("/start", json={"point": "20"})
        self.assertEqual(self.settle()["status"], 409)
        self.assertFalse([c for c in self.calls if c[1].endswith("/release")])

    def test_a_recording_in_progress_is_no_demo_and_blocks_a_start(self):
        self.runs = [{"match_id": "rec-a", "fixture": "a", "status": "live", "hold_seconds": 1200.0}]
        state = self.client.get("/state").json()
        self.assertFalse(state["live"])
        self.assertEqual(state["recording"], [{"match_id": "rec-a"}])  # the viewer hides it: it stops at 20′
        self.assertEqual(self.client.post("/start").status_code, 409)
        self.assertFalse(self.purged())  # the recording is untouched

    def test_a_failed_restore_purges_the_waiting_runs_everywhere(self):
        self.seed()
        self.refuse_restore = {"backend"}
        self.refuse_status = 500
        self.client.post("/start", json={"point": "20"})
        self.assertEqual(self.settle()["status"], 503)
        self.assertEqual({m for _, m in self.purged()}, {"m0", "m1", "m2"})
        self.assertFalse([c for c in self.calls if c[1].endswith("/release")])

    def test_an_owner_failing_its_purge_after_a_failed_restore_still_frees_every_run(self):
        self.seed()
        self.refuse_restore, self.refuse_status, self.refuse_purge = {"backend"}, 500, {"etl-stream"}
        self.client.post("/start", json={"point": "20"})
        self.assertEqual(self.settle()["status"], 503)
        self.assertEqual({m for host, m in self.purged() if host == "feed"}, {"m0", "m1", "m2"})
        self.assertEqual(self.runs, [])  # no run left waiting on a seed that will not come

    def test_status_callers_share_one_check_per_cache_window(self):
        self.client.get("/status")
        probes = len([c for c in self.calls if c[1] == "/health"])
        for _ in range(20):
            self.client.get("/status")
        self.assertEqual(len([c for c in self.calls if c[1] == "/health"]), probes)  # no fan-out per caller

    def test_status_reports_each_stage_from_real_checks(self):
        self.addCleanup(setattr, demo_control, "STATUS_CACHE_SECONDS", demo_control.STATUS_CACHE_SECONDS)
        demo_control.STATUS_CACHE_SECONDS = 0
        self.down = {"narrative-live"}
        self.client.post("/start")
        self.settle()
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

    def test_skip_ahead_is_offered_while_a_demo_plays_and_forwards_to_the_feed(self):
        self.settings["skip_targets"] = [{"id": "20", "label": "+20′", "minutes": 20}]
        self.assertEqual(self.client.get("/state").json()["skips"], [])  # nothing playing
        self.assertEqual(self.client.post("/skip", json={"target": "20"}).status_code, 409)
        self.client.post("/start")
        self.settle()
        self.assertEqual(self.client.get("/state").json()["skips"], [{"id": "20", "label": "+20′"}])
        moved = self.client.post("/skip", json={"target": "20"})
        self.assertEqual((moved.status_code, moved.json()["skipped_seconds"]), (200, 600))
        self.assertIn(("feed", "/demo/skip", {"target": "20"}), self.calls)
        self.assertEqual(self.client.post("/skip", json={}).status_code, 422)

    def test_state_names_the_main_game_to_open_by_default(self):
        self.assertEqual([self.client.get("/state").json()[k] for k in ("main_fixture", "main_match_id")], ["b", None])
        self.client.post("/start")
        self.settle()
        self.assertEqual(self.client.get("/state").json()["main_match_id"], "m1")  # fixture "b"
        del self.settings["main_fixture"]  # a feed without the setting: its first fixture
        self.assertEqual(self.client.get("/state").json()["main_fixture"], "b")

    def test_capture_refuses_held_runs_of_another_point(self):
        self.runs = [{"match_id": "rec-a", "fixture": "a", "status": "live", "hold_seconds": 1200.0,
                      "held_at": "ht", "video_seconds": 1200.0, "seq": 7}]
        http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=self.runs)))
        with self.assertRaises(SystemExit) as raised:
            demo_control.capture(http, "20", log=lambda _: None, timeout=0)
        self.assertIn("ht, not 20", str(raised.exception))

    def test_state_marks_points_without_a_seed_not_ready(self):
        self.assertEqual([p["ready"] for p in self.client.get("/state").json()["points"]], [True, False])

    def test_state_marks_a_stale_seed_not_ready(self):
        manifest = self.seed()
        self.assertEqual([p["ready"] for p in self.client.get("/state").json()["points"]], [True, True])
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), "format": 1}))
        self.assertEqual([p["ready"] for p in self.client.get("/state").json()["points"]], [True, False])

    def test_a_viewer_at_the_picker_wakes_every_owner_at_most_once_a_keep_warm_round(self):
        def woken():
            for _ in range(100):  # the wake-ups run on a worker
                hosts = {host for host, path, _ in self.calls if path == "/health"}
                if len(hosts) == 4:
                    return hosts
                time.sleep(0.01)
            return {host for host, path, _ in self.calls if path == "/health"}
        self.client.get("/state")
        self.assertEqual(woken(), {"feed", "etl-stream", "narrative-live", "backend"})
        self.calls.clear()
        self.client.get("/state")
        self.now += demo_control.KEEP_WARM_SECONDS - 1
        self.client.get("/state")
        time.sleep(0.05)
        self.assertEqual([path for _, path, _ in self.calls if path == "/health"], [])
        self.now += 1
        self.client.get("/state")
        self.assertEqual(woken(), {"feed", "etl-stream", "narrative-live", "backend"})

    def test_keep_warm_touches_every_owner_only_while_a_demo_is_live(self):
        warm = self.client.app.state.keep_warm_once
        self.calls.clear()
        self.assertFalse(warm())
        self.assertEqual([path for _, path, _ in self.calls if path == "/health"], [])
        self.runs = [{"match_id": "m0", "fixture": "a", "status": "live"}]
        self.calls.clear()
        self.assertTrue(warm())
        self.assertEqual({host for host, path, _ in self.calls if path == "/health"},
                         {"feed", "etl-stream", "narrative-live", "backend"})


if __name__ == "__main__":
    unittest.main()
