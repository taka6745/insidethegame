"""Feed runs on a virtual clock: send order, pacing, HLS edge and purge."""
import asyncio
import dataclasses
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from feed.routes.http import create_app
from feed.services.feed import FeedError, FeedService
from feed.tests.support import FakeClock, FakeSink, MemoryRepository, riverton, media

START = datetime(2026, 10, 20, 15, 0, 10, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 10, 20, 15, 2, tzinfo=timezone.utc)  # next-minute from START


class FeedTestCase(unittest.IsolatedAsyncioTestCase):
    segments = 0

    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        stream = riverton()
        if self.segments:
            stream = dataclasses.replace(stream, media=media(self.tmp / "source", self.segments))
        self.stream = stream
        self.clock = FakeClock(START)
        self.sink = FakeSink(self.clock)
        self.repository = MemoryRepository(self.clock)
        self.live = self.tmp / "live"
        self.service = FeedService(self.repository, {stream.fixture: stream}, sink=self.sink, clock=self.clock,
                                   live_root=self.live)
        await self.service.start()

    async def asyncTearDown(self):
        await self.service.close()

    async def run_to(self, seconds_after_kickoff, step=None):
        target = KICKOFF + timedelta(seconds=seconds_after_kickoff)
        while self.clock.now() < target:
            remaining = (target - self.clock.now()).total_seconds()
            await self.clock.advance(min(step or remaining, remaining), self.service)

    async def start_run(self):
        run = await self.service.create_run("riverton-forgeham")
        await self.clock.settle(self.service)
        return run


class RunTests(FeedTestCase):
    async def test_ma1_leads_kickoff_then_events_follow(self):
        run = await self.start_run()
        self.assertEqual(run["kickoff"], "2026-10-20T15:02:00Z")
        self.assertEqual(run["match_id"], f"riverton-forgeham-{run['run_id'].replace('-', '')[:8]}")
        self.assertEqual(self.sink.sent, [])  # 110 s before kickoff: nothing yet.
        await self.run_to(-60.5)
        self.assertEqual(self.sink.sent, [])
        await self.run_to(-59)
        (key, ma1, sent_at), = self.sink.sent
        self.assertEqual((key, ma1["feed"], ma1["matchId"], ma1["runId"]), (run["match_id"], "MA1", run["match_id"],
                                                                               run["run_id"]))
        self.assertEqual((ma1["fixture"], ma1["sourceMatchId"]), ("riverton-forgeham", "product-demo-match"))
        self.assertEqual(ma1["scheduledKickoff"], "2026-10-20T15:02:00.000Z")
        self.assertFalse(ma1["capabilities"]["video"])
        self.assertEqual(set(ma1["branding"]), {"riverton", "forgeham"})
        self.assertEqual((await self.service.runs())[0]["status"], "scheduled")
        await self.run_to(0.3)
        first = self.sink.bodies(kind="MatchEvent")
        self.assertEqual([b["seq"] for b in first], [1, 2, 3])  # video 0.0, 0.24, 0.24
        self.assertEqual(first[0]["timeStamp"], "2026-10-20T15:02:00.000Z")
        self.assertEqual(first[1]["event"]["match_id"], run["match_id"])
        self.assertEqual((await self.service.runs())[0]["status"], "live")

    async def test_send_order_seq_and_pacing(self):
        run = await self.start_run()
        await self.run_to(900, step=37)
        sent = [(b, at) for key, b, at in self.sink.sent]
        self.assertEqual(sent[0][0]["feed"], "MA1")
        seqs, last_seq, ma3 = [], 0, []
        for body, at in sent[1:]:
            video = (at - KICKOFF).total_seconds()
            if body.get("type") == "MatchEvent":
                self.assertEqual(body["seq"], body["event"]["sequence"])
                self.assertLessEqual(body["event"]["video_seconds"], video)  # never ahead of the clock
                seqs.append(body["seq"])
                last_seq = body["seq"]
            elif body["feed"] == "MA3":
                self.assertEqual(body["eventSeq"], last_seq)  # straight after its event
                ma3.append(body["seq"])
            else:
                self.assertEqual(body["feed"], "POS")
                self.assertEqual(body["eventSeq"], last_seq)
                self.assertLessEqual(body["videoSeconds"], video)
                if last_seq < len(self.stream.events):  # POS precedes events at the same time
                    self.assertLessEqual(body["videoSeconds"], self.stream.events[last_seq]["video_seconds"])
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))
        self.assertEqual(ma3, list(range(1, len(ma3) + 1)))
        due = sum(1 for e in self.stream.events if e["video_seconds"] <= 900)
        self.assertEqual(len(seqs), due)
        self.assertEqual((await self.service.runs())[0]["seq"], due)
        self.assertTrue(all(key == run["match_id"] for key, _, _ in self.sink.sent))

    async def test_full_match_finishes(self):
        await self.start_run()
        await self.run_to(self.stream.duration_seconds + 1, step=600)
        events = self.sink.bodies(kind="MatchEvent")
        self.assertEqual([b["seq"] for b in events], list(range(1, len(self.stream.events) + 1)))
        self.assertEqual(len(self.sink.bodies(kind="POS")), len(self.stream.pos))
        self.assertEqual(len(self.sink.bodies(kind="MA3")), len(self.stream.ma3))
        self.assertEqual(events[-1]["event"]["event_type"], "period_end")
        self.assertEqual((await self.service.runs())[0]["status"], "finished")

    async def test_two_runs_interleave_with_their_own_seq(self):
        first = await self.start_run()
        await self.run_to(-30)
        second = await self.start_run()  # next minute after now: kicks off 60 s later
        self.assertEqual(second["kickoff"], "2026-10-20T15:03:00Z")
        await self.run_to(120, step=3)
        keys = [key for key, _, _ in self.sink.sent]
        self.assertEqual(set(keys), {first["match_id"], second["match_id"]})
        self.assertLess(keys.index(second["match_id"]), len(keys) - 1 - keys[::-1].index(first["match_id"]))
        for run, lead in ((first, 120), (second, 60)):
            bodies = self.sink.bodies(run["match_id"])
            self.assertTrue(all(b["matchId"] == run["match_id"] for b in bodies))
            seqs = [b["seq"] for b in bodies if b.get("type") == "MatchEvent"]
            self.assertEqual(seqs, list(range(1, len(seqs) + 1)))
            self.assertEqual(len(seqs), sum(1 for e in self.stream.events if e["video_seconds"] <= lead))

    async def test_backlog_goes_out_in_capped_sends_and_a_refused_send_is_retried(self):
        MAX_SEND = self.service.policy.max_items
        sizes, refuse = [], [True]
        send = self.sink.send

        async def throttled(key, bodies):
            sizes.append(len(bodies))
            if refuse.pop() if refuse else False:  # The first send after the stall is refused.
                raise RuntimeError("server-busy")
            await send(key, bodies)
        self.sink.send = throttled
        run = await self.start_run()
        await self.run_to(600)  # One jump: ten minutes due at once.
        await self.run_to(605)  # The retry after the refusal.
        self.assertLessEqual(max(sizes), MAX_SEND)
        self.assertGreater(len(sizes), 3)
        seqs = [b["seq"] for b in self.sink.bodies(run["match_id"], "MatchEvent")]
        self.assertEqual(seqs, list(range(1, sum(1 for e in self.stream.events if e["video_seconds"] <= 605) + 1)))

    async def test_send_policy_comes_from_settings_and_caps_sends(self):
        from feed.services.run import SendPolicy
        policy = SendPolicy.from_env({"FEED_SEND_MAX_ITEMS": "25", "FEED_SEND_THROTTLE_WAIT_SECONDS": "3"})
        self.assertEqual(policy, SendPolicy(max_items=25, throttle_wait=3.0))
        await self.service.close()
        self.service = FeedService(self.repository, {self.stream.fixture: self.stream}, sink=self.sink,
                                   clock=self.clock, live_root=self.live, policy=policy)
        await self.service.start()
        sizes, send = [], self.sink.send

        async def recorded(key, bodies):
            sizes.append(len(bodies))
            await send(key, bodies)
        self.sink.send = recorded
        await self.start_run()
        await self.run_to(300)
        self.assertEqual(max(sizes), 25)

    async def test_throttling_backs_off_and_resumes_without_gaps_or_duplicates(self):
        from feed.adapters.eventhubs import SendError
        THROTTLE_WAIT = self.service.policy.throttle_wait
        attempts, refusals = [], [3, 0, 0]  # A partial send (3 went out), then two refusals.
        send = self.sink.send

        async def throttled(key, bodies):
            attempts.append(self.clock.now())
            if refusals:
                sent = refusals.pop(0)
                await send(key, bodies[:sent])
                raise SendError(sent, throttled=True)
            await send(key, bodies)
        run = await self.start_run()
        await self.run_to(30)
        self.sink.send = throttled
        await self.run_to(90)  # One jump: a minute's backlog, its first send partly refused.
        await self.run_to(150, step=1)
        refused = attempts[:4]
        self.assertTrue(all((b - a).total_seconds() >= THROTTLE_WAIT for a, b in zip(refused, refused[1:])))
        seqs = [b["seq"] for b in self.sink.bodies(run["match_id"], "MatchEvent")]
        self.assertEqual(seqs, list(range(1, sum(1 for e in self.stream.events if e["video_seconds"] <= 150) + 1)))
        self.assertEqual(len(self.sink.bodies(kind="MA1")), 1)

    async def test_a_large_flush_throttled_while_it_progresses_waits_only_the_throttle_wait(self):
        from feed.adapters.eventhubs import SendError
        THROTTLE_WAIT = self.service.policy.throttle_wait
        attempts, send = [], self.sink.send

        async def throttled(key, bodies):  # every send gets half through, then the hub asks to slow down
            attempts.append(self.clock.now())
            sent = max(1, len(bodies) // 2)
            await send(key, bodies[:sent])
            raise SendError(sent, throttled=True)
        run = await self.start_run()
        await self.run_to(30)
        self.sink.send = throttled
        await self.run_to(600)  # ten minutes due at once, like a skip ahead
        await self.run_to(700, step=1)
        gaps = [(b - a).total_seconds() for a, b in zip(attempts, attempts[1:])]
        self.assertGreater(len(gaps), 5)
        self.assertTrue(all(THROTTLE_WAIT <= g < 2 * THROTTLE_WAIT for g in gaps), gaps)  # progress: no escalation
        seqs = [b["seq"] for b in self.sink.bodies(run["match_id"], "MatchEvent")]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    async def test_restart_resumes_without_resending(self):
        run = await self.start_run()
        await self.run_to(30)
        await self.service.close()
        self.service = FeedService(self.repository, {self.stream.fixture: self.stream}, sink=self.sink,
                                   clock=self.clock, live_root=self.live)
        await self.service.start()
        await self.run_to(60)
        seqs = [b["seq"] for b in self.sink.bodies(run["match_id"], "MatchEvent")]
        self.assertEqual(seqs, list(range(1, sum(1 for e in self.stream.events if e["video_seconds"] <= 60) + 1)))
        self.assertEqual(len(self.sink.bodies(kind="MA1")), 1)

    async def test_kickoff_validation_and_no_seek(self):
        with self.assertRaises(FeedError) as error:
            await self.service.create_run("nope")
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(FeedError) as error:
            await self.service.create_run("riverton-forgeham", "2026-10-20T14:00:00Z")
        self.assertEqual(error.exception.status, 422)
        with self.assertRaises(FeedError) as error:
            await self.service.create_run("riverton-forgeham", start_seconds=600)
        self.assertEqual(error.exception.status, 422)
        self.service.allow_seek = True  # dev-only
        run = await self.service.create_run("riverton-forgeham", start_seconds=600)
        await self.clock.settle(self.service)
        self.assertEqual(run["status"], "scheduled")
        self.assertEqual(self.sink.bodies(run["match_id"], "MatchEvent")[-1]["seq"],
                         sum(1 for e in self.stream.events if e["video_seconds"] <= 600))


class MediaTests(FeedTestCase):
    segments = 10  # 20 s of fake footage

    async def test_segments_never_published_past_the_clock(self):
        run = await self.start_run()
        directory = self.live / run["match_id"]
        await self.run_to(1.9)
        self.assertFalse(directory.exists())
        for seconds in (2.0, 3.5, 7.9, 8.0, 13.3):
            await self.run_to(seconds)
            listed = [line for line in (directory / "live.m3u8").read_text().splitlines() if line.endswith(".ts")]
            self.assertEqual(len(listed), int(seconds // 2))
            self.assertEqual(sorted(p.name for p in directory.glob("*.ts")), listed)
        self.assertNotIn("#EXT-X-ENDLIST", (directory / "live.m3u8").read_text())
        await self.run_to(20)
        self.assertIn("#EXT-X-ENDLIST", (directory / "live.m3u8").read_text())
        self.assertTrue(self.sink.bodies(kind="MA1")[0]["capabilities"]["video"])

    async def test_restart_keeps_the_published_prefix(self):
        run = await self.start_run()
        await self.run_to(5)
        await self.service.close()
        self.service = FeedService(self.repository, {self.stream.fixture: self.stream}, sink=self.sink,
                                   clock=self.clock, live_root=self.live)
        await self.service.start()
        self.assertEqual(self.service.tasks[run["match_id"]][0].playlist.published, 2)  # kept, not re-copied
        await self.run_to(9)
        listed = [line for line in (self.live / run["match_id"] / "live.m3u8").read_text().splitlines()
                  if line.endswith(".ts")]
        self.assertEqual(listed, [f"{i:05d}.ts" for i in range(4)])

    async def test_purge_waits_for_an_in_flight_segment_copy(self):
        run = await self.start_run()
        task, gate = self.service.tasks[run["match_id"]][0], threading.Event()
        publish = task.playlist.publish
        task.playlist.publish = lambda clock: gate.wait(5) and publish(clock)
        self.clock.t = KICKOFF + timedelta(seconds=4.5)
        async with self.clock._changed:
            self.clock._changed.notify_all()
        await asyncio.sleep(0.05)  # The run is now copying segments in a worker thread.
        purge = asyncio.create_task(self.service.purge(run["match_id"]))
        await asyncio.sleep(0.05)
        gate.set()
        await purge
        await asyncio.sleep(0.05)
        self.assertFalse((self.live / run["match_id"]).exists())

    async def test_playlist_404_before_first_segment_and_after_purge(self):
        run = await self.start_run()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(create_app(self.service, self.live)),
                                   base_url="http://feed")
        playlist = f"/hls/{run['match_id']}/live.m3u8"
        self.assertEqual((await client.get(playlist)).status_code, 404)
        await self.run_to(1)
        self.assertEqual((await client.get(playlist)).status_code, 404)
        await self.run_to(4.5)
        response = await client.get(playlist)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertEqual((await client.get(f"/hls/{run['match_id']}/00001.ts")).status_code, 200)
        self.assertEqual((await client.get(f"/hls/{run['match_id']}/00002.ts")).status_code, 404)  # not played
        self.assertEqual((await client.get("/hls/..%2Fsource/match.m3u8")).status_code, 404)
        response = await client.post("/admin/matches/purge", json={"match_id": run["match_id"]})
        self.assertEqual(response.json()["purged"], {"runs": 1, "hls_files": 3})
        self.assertEqual((await client.get(playlist)).status_code, 404)
        self.assertEqual((await client.get(f"/hls/{run['match_id']}/00000.ts")).status_code, 404)
        await client.aclose()


class PurgeTests(FeedTestCase):
    async def test_purge_stops_run_and_tombstones(self):
        run = await self.start_run()
        await self.run_to(30)
        sent = len(self.sink.sent)
        result = await self.service.purge(run["match_id"])
        self.assertEqual(result, {"match_ids": [run["match_id"]], "purged": {"runs": 1, "hls_files": 0}})
        self.assertEqual(self.service.tasks, {})
        self.assertEqual(await self.service.runs(), [])
        await self.run_to(60)
        self.assertEqual(len(self.sink.sent), sent)  # nothing more for a purged match
        self.assertIn(run["match_id"], self.repository.tombstones)
        self.assertIsNone(self.repository.create_run("x", run["match_id"], "riverton-forgeham", KICKOFF))
        again = await self.service.purge(run["match_id"])  # idempotent
        self.assertEqual(again["purged"], {"runs": 0, "hls_files": 0})
        unknown = await self.service.purge("riverton-forgeham-00000000")
        self.assertEqual(unknown["purged"], {"runs": 0, "hls_files": 0})
        self.assertIn("riverton-forgeham-00000000", self.repository.tombstones)

    async def test_purge_all_sets_cutoff(self):
        first, second = await self.start_run(), await self.start_run()
        result = await self.service.purge(everything=True)
        self.assertEqual(result["match_ids"], sorted([first["match_id"], second["match_id"]]))
        self.assertEqual(result["purged"]["runs"], 2)
        self.assertEqual(self.repository.cutoff, self.clock.now())
        await self.clock.advance(1, self.service)
        third = await self.start_run()  # new runs after the cut-off still work
        self.assertEqual([r["match_id"] for r in await self.service.runs()], [third["match_id"]])

    async def test_purge_request_validation(self):
        client = httpx.AsyncClient(transport=httpx.ASGITransport(create_app(self.service, self.live)),
                                   base_url="http://feed")
        for body in ({}, {"all": False}, {"all": True, "match_id": "a"}, {"match_id": "../x"}):
            self.assertEqual((await client.post("/admin/matches/purge", json=body)).status_code, 422, body)
        recordings = (await client.get("/recordings")).json()
        self.assertEqual([r["fixture"] for r in recordings], ["riverton-forgeham"])
        self.assertNotIn("events", recordings[0])
        created = await client.post("/runs", json={"fixture": "riverton-forgeham", "kickoff": "next-minute"})
        self.assertEqual(created.status_code, 201)
        self.assertEqual((await client.post("/runs", json={"fixture": "nope"})).status_code, 404)
        await client.aclose()


class DemoTests(FeedTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        other = dataclasses.replace(self.stream, fixture="redcastle-portalbion")
        self.service.streams[other.fixture] = other
        self.service.seeds = True  # DEMO_SEEDS=1
        self.points = self.repository.demo["start_points"]
        await self.service.save_demo_settings(self.settings(["riverton-forgeham", "redcastle-portalbion"], 120, 2), 1)

    def settings(self, fixtures, stagger, cap, points=None):
        return {"fixtures": fixtures, "stagger_seconds": stagger, "max_active_runs": cap,
                "start_points": points or self.points}

    async def test_demo_starts_the_fixtures_staggered_once_under_concurrent_clicks(self):
        results = await asyncio.gather(*(self.service.start_demo() for _ in range(5)))
        self.assertEqual(sum(r["started"] for r in results), 1)
        runs = await self.service.runs()
        self.assertEqual([(r["fixture"], r["kickoff"]) for r in runs],
                         [("riverton-forgeham", "2026-10-20T15:02:00Z"), ("redcastle-portalbion", "2026-10-20T15:04:00Z")])
        for result in results:
            self.assertEqual({r["match_id"] for r in result["runs"]}, {r["match_id"] for r in runs})

    async def test_the_main_game_starts_first_and_leads_the_saved_order(self):
        saved = await self.service.save_demo_settings(
            {**self.settings(["riverton-forgeham", "redcastle-portalbion"], 120, 3), "main_fixture": "redcastle-portalbion"}, 2)
        self.assertEqual((saved["main_fixture"], saved["fixtures"]),
                         ("redcastle-portalbion", ["redcastle-portalbion", "riverton-forgeham"]))
        result = await self.service.start_demo()
        self.assertEqual(result["main_fixture"], "redcastle-portalbion")
        self.assertEqual([(r["fixture"], r["kickoff"]) for r in await self.service.runs()],
                         [("redcastle-portalbion", "2026-10-20T15:02:00Z"), ("riverton-forgeham", "2026-10-20T15:04:00Z")])
        with self.assertRaises(FeedError) as error:
            await self.service.save_demo_settings({**self.settings(["riverton-forgeham"], 0, 3), "main_fixture": "nope"}, 3)
        self.assertEqual(error.exception.status, 422)

    async def test_the_cap_refuses_another_run_while_the_demo_is_on(self):
        await self.service.start_demo()
        with self.assertRaises(FeedError) as error:
            await self.service.create_run("riverton-forgeham")
        self.assertEqual(error.exception.status, 409)

    async def test_a_new_demo_purges_finished_runs_only_after_they_finish(self):
        first = await self.service.start_demo()
        await self.run_to(self.stream.duration_seconds + 121, step=600)
        self.assertTrue(all(r["status"] == "finished" for r in await self.service.runs()))
        second = await self.service.start_demo()
        self.assertTrue(second["started"])
        old = {r["match_id"] for r in first["runs"]}
        self.assertTrue(old <= self.repository.tombstones)
        self.assertFalse(old & {r["match_id"] for r in await self.service.runs()})

    async def test_settings_are_validated_and_revision_checked(self):
        twice = [self.points[0], self.points[0]]
        for args in ((["nope"], 0, 3), (["riverton-forgeham", "riverton-forgeham"], 0, 3),
                     (["riverton-forgeham", "redcastle-portalbion"], 0, 1), (["riverton-forgeham"], 0, 3, twice)):
            with self.assertRaises(FeedError) as error:
                await self.service.save_demo_settings(self.settings(*args), 2)
            self.assertEqual(error.exception.status, 422, args)
        with self.assertRaises(FeedError) as error:
            await self.service.save_demo_settings(self.settings(["riverton-forgeham"], 0, 3), 1)  # stale revision
        self.assertEqual(error.exception.status, 409)

    async def test_a_later_start_point_needs_a_seed_then_resumes_from_it(self):
        with self.assertRaises(FeedError) as error:
            await self.service.start_demo("20")
        self.assertEqual(error.exception.status, 409)
        points = [self.points[0], {**self.points[1], "seed": "seed-test"}]
        await self.service.save_demo_settings(self.settings(["riverton-forgeham"], 120, 3, points), 2)
        result = await self.service.start_demo("20")
        run = result["runs"][0]
        offset = self.stream.video_at(1, 20)
        self.assertTrue(run["awaiting_restore"])  # nothing goes out until every owner restored the seed
        await self.run_to(5, step=1)
        self.assertFalse(self.sink.bodies(run["match_id"]))
        self.assertEqual(await self.service.start_demo("20"), {"started": False, "runs": [await self._run(run)]})
        run = await self.service.release(run["match_id"], (KICKOFF - self.clock.now()).total_seconds() + 60)
        self.assertEqual(run, await self.service.release(run["match_id"]))  # idempotent
        self.assertEqual(run["kickoff"], (KICKOFF + timedelta(seconds=60 - offset)).isoformat().replace("+00:00", "Z"))
        await self.run_to(65, step=1)
        bodies = self.sink.bodies(run["match_id"])
        self.assertFalse([b for b in bodies if b.get("feed") == "MA1" or b.get("type") == "MA1"])  # from the seed
        seqs = [b["seq"] for b in bodies if b.get("type") == "MatchEvent"]
        first = sum(1 for e in self.stream.events if e["video_seconds"] < offset) + 1
        self.assertEqual(seqs[0], first)  # nothing before the start point is re-sent
        self.assertTrue(all(self.stream.events[s - 1]["video_seconds"] <= offset + 5 for s in seqs))  # nothing ahead

    async def test_a_demo_that_fails_partway_leaves_no_runs(self):
        await self.service.save_demo_settings(self.settings(["riverton-forgeham", "redcastle-portalbion"], 120, 3), 2)
        create, calls = self.service._create, []

        async def failing(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise FeedError(503, "Could not mint a new matchId; retry.")
            return await create(*args, **kwargs)
        self.service._create = failing
        with self.assertRaises(FeedError):
            await self.service.start_demo()
        self.service._create = create
        self.assertEqual(await self.service.runs(), [])
        self.assertTrue((await self.service.start_demo())["started"])

    async def _run(self, run):
        return next(r for r in await self.service.runs() if r["match_id"] == run["match_id"])

    async def test_a_held_run_stops_at_its_point(self):
        run = await self.service.create_run("riverton-forgeham", hold_point="20")
        self.assertEqual(run["held_at"], "20")  # demo control's capture checks it
        hold = self.stream.video_at(1, 20)
        await self.run_to(hold + 30, step=10)
        sent = [b for b in self.sink.bodies(run["match_id"]) if b.get("type") == "MatchEvent"]
        self.assertTrue(sent)
        self.assertTrue(all(self.stream.events[b["seq"] - 1]["video_seconds"] < hold for b in sent))
        self.assertEqual((await self._run(run))["video_seconds"], round(hold, 3))
        # A run resumed from that point carries on after exactly the seq the held run stopped at (the seed's).
        resumed = await self.service.create_run("riverton-forgeham", resume_point="20")
        self.assertEqual(((await self._run(run))["seq"], resumed["awaiting_restore"]), (resumed["seq"], True))
        self.assertEqual(resumed["seq"], max(b["seq"] for b in sent))

    async def test_without_demo_seeds_there_is_no_seed_path(self):
        """A production release (DEMO_SEEDS off): no held or resumed runs, no seeded starts, no release route."""
        self.service.seeds = False
        points = [self.points[0], {**self.points[1], "seed": "seed-test"}]
        await self.service.save_demo_settings(self.settings(["riverton-forgeham"], 120, 3, points), 2)
        for kwargs in ({"hold_point": "20"}, {"resume_point": "20"}):
            with self.assertRaises(FeedError) as error:
                await self.service.create_run("riverton-forgeham", **kwargs)
            self.assertEqual(error.exception.status, 403)
        with self.assertRaises(FeedError) as error:
            await self.service.start_demo("20")
        self.assertEqual(error.exception.status, 409)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(create_app(self.service, self.live)),
                                   base_url="http://feed")
        self.assertIn((await client.post("/runs/riverton-forgeham-0000aaaa/release")).status_code, (404, 405))
        await client.aclose()

    async def test_skip_ahead_moves_every_run_on_together_and_sends_only_up_to_the_new_clock(self):
        await self.service.start_demo()
        await self.run_to(240, step=10)  # both live: the second kicked off at +120 s
        before = {r["match_id"]: r for r in await self.service.runs()}
        result = await self.service.skip_demo("10")
        self.assertEqual(result["skipped_seconds"], 600)
        await self.clock.settle(self.service)
        await self.clock.advance(1, self.service)
        for run in await self.service.runs():
            old = before[run["match_id"]]
            self.assertEqual(datetime.fromisoformat(run["kickoff"].replace("Z", "+00:00")),
                             datetime.fromisoformat(old["kickoff"].replace("Z", "+00:00")) - timedelta(seconds=600))
            clock = (self.clock.now() - datetime.fromisoformat(run["kickoff"].replace("Z", "+00:00"))).total_seconds()
            seqs = [b["seq"] for b in self.sink.bodies(run["match_id"], "MatchEvent")]
            self.assertEqual(seqs, list(range(1, len(seqs) + 1)))  # in order, none twice, none skipped
            self.assertTrue(all(self.stream.events[s - 1]["video_seconds"] <= clock for s in seqs))  # no future
            due = sum(1 for e in self.stream.events if e["video_seconds"] <= clock - 1)
            self.assertGreaterEqual(len(seqs), due)  # everything due by the new clock went out

    async def test_skip_to_a_point_rounds_up_to_whole_minutes_on_the_main_clock(self):
        await self.service.start_demo()
        await self.run_to(130, step=10)
        result = await self.service.skip_demo("to-20")
        main_clock = 130
        self.assertEqual(result["skipped_seconds"] % 60, 0)
        self.assertGreaterEqual(main_clock + result["skipped_seconds"], self.stream.video_at(1, 20))
        self.assertLess(main_clock + result["skipped_seconds"] - 60, self.stream.video_at(1, 20))
        with self.assertRaises(FeedError) as error:  # already past it
            await self.service.skip_demo("to-20")
        self.assertEqual(error.exception.status, 409)

    async def test_skip_ahead_is_refused_without_a_playing_demo_or_demo_seeds(self):
        for target, status in (("10", 409), ("nope", 404)):
            with self.assertRaises(FeedError) as error:
                await self.service.skip_demo(target)
            self.assertEqual(error.exception.status, status)
        await self.service.create_run("riverton-forgeham", hold_point="20")  # a seed recording
        await self.run_to(30, step=10)
        with self.assertRaises(FeedError) as error:
            await self.service.skip_demo("10")
        self.assertEqual(error.exception.status, 409)
        self.service.seeds = False
        with self.assertRaises(FeedError) as error:
            await self.service.skip_demo("10")
        self.assertEqual(error.exception.status, 403)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(create_app(self.service, self.live)),
                                   base_url="http://feed")
        self.assertIn((await client.post("/demo/skip", json={"target": "10"})).status_code, (404, 405))
        await client.aclose()
        settings = await self.service.demo_settings()  # nothing to offer, and a round-trip save keeps the saved ones
        self.assertEqual(settings["skip_targets"], [])
        await self.service.save_demo_settings({k: v for k, v in settings.items() if k != "revision"},
                                              settings["revision"])
        self.assertEqual([t["id"] for t in self.repository.demo["skip_targets"]], ["10", "to-20"])

    async def test_skip_ahead_keeps_a_throttled_runs_back_off(self):
        await self.service.start_demo()
        await self.run_to(60, step=10)
        task = next(iter(self.service.tasks.values()))[0]
        task.failures, task.retry_at = 3, self.clock.now() + timedelta(seconds=30)
        await self.service.skip_demo("10")
        moved = next(iter(self.service.tasks.values()))[0]
        self.assertIsNot(moved, task)
        self.assertEqual((moved.failures, moved.retry_at), (task.failures, task.retry_at))

    async def test_skip_targets_are_validated_and_kept_when_a_client_leaves_them_out(self):
        bad = ([{"id": "a", "label": "A"}], [{"id": "a", "label": "A", "minutes": 5, "point": "20"}],
               [{"id": "a", "label": "A", "point": "nope"}],
               [{"id": "a", "label": "A", "minutes": 5}, {"id": "a", "label": "B", "minutes": 6}])
        for skips in bad:
            with self.assertRaises(FeedError) as error:
                await self.service.save_demo_settings({**self.settings(["riverton-forgeham"], 0, 3), "skip_targets": skips}, 2)
            self.assertEqual(error.exception.status, 422, skips)
        kept = await self.service.save_demo_settings(self.settings(["riverton-forgeham"], 0, 3), 2)
        self.assertEqual(kept["skip_targets"], self.repository.demo["skip_targets"])
        self.assertEqual([t["id"] for t in kept["skip_targets"]], ["10", "to-20"])

    async def test_http_start_is_201_then_200(self):
        client = httpx.AsyncClient(transport=httpx.ASGITransport(create_app(self.service, self.live)),
                                   base_url="http://feed")
        self.assertEqual((await client.post("/demo/start")).status_code, 201)
        again = await client.post("/demo/start")
        self.assertEqual((again.status_code, again.json()["started"], len(again.json()["runs"])), (200, False, 2))
        self.assertEqual((await client.get("/demo")).json()["max_active_runs"], 2)
        await client.aclose()


if __name__ == "__main__":
    unittest.main()


class MediaRootTests(unittest.TestCase):
    def test_one_media_root_is_searched_per_fixture(self):
        from feed.adapters.recordings import discover
        from feed.tests.support import RECORDINGS

        root = Path(tempfile.mkdtemp())
        media(root / "riverton-forgeham" / "hls")
        (root / "unrelated").mkdir()  # anything else under the root is ignored
        found = discover(RECORDINGS, root)
        self.assertEqual(found["riverton-forgeham"].media, root / "riverton-forgeham" / "hls")
        self.assertTrue(all(s.media is None for f, s in found.items() if f != "riverton-forgeham"))
        self.assertTrue(all(s.media is None for s in discover(RECORDINGS, None).values()))


class EventHubsSinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_refused_batch_reports_what_went_out_and_throttling(self):
        from azure.eventhub import EventDataBatch
        from feed.adapters.eventhubs import EventHubsSink, SendError

        class Producer:  # Batches of two; the second send is throttled.
            def __init__(self):
                self.sent = []

            async def create_batch(self, partition_key):
                return EventDataBatch(max_size_in_bytes=300, partition_key=partition_key)

            async def send_batch(self, batch):
                if self.sent:
                    raise RuntimeError("Error condition: com.microsoft:server-busy")
                self.sent.append(len(batch))

        sink = EventHubsSink("unused")
        sink.producer = Producer()
        with self.assertRaises(SendError) as error:
            await sink.send("m", [{"seq": i, "pad": "x" * 60} for i in range(5)])
        self.assertEqual((error.exception.sent, error.exception.throttled), (sink.producer.sent[0], True))
        self.assertGreater(error.exception.sent, 0)
