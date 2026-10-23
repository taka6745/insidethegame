"""Local stream worker: incremental windows match the reference pipeline; redelivery and restarts are safe."""
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from reference import pipeline
from local_stream.processor import Output, StreamProcessor
from local_stream.worker import StreamWorker
from support import Clock, FakeRepository, bodies, canonical

STREAM = Path(__file__).resolve().parents[2] / "data-generation" / "recordings" / "riverton-forgeham-grf.opta-stream.jsonl"
MESSAGES = [json.loads(line) for line in STREAM.read_text(encoding="utf-8").splitlines()]


def run(worker, messages, start=0, batch=50):
    for i in range(start, len(messages), batch):
        worker.handle("0", [(i + j, json.dumps(m)) for j, m in enumerate(messages[i:i + batch])])


def finish(worker, clock):
    clock.now += 1000
    worker.handle("0", [])


def test_processor_matches_reference_on_grf_stream():
    processor, out = StreamProcessor(60), Output()
    for m in MESSAGES:
        out.extend(processor.process(m))
    out.extend(processor.flush())
    expected = pipeline.stream_outputs(MESSAGES, 60)
    for table in ("matches", "rawEvents", "keyEvents", "minuteStats"):
        assert canonical(out.rows[table]) == canonical(expected[table]), table
    assert bodies(out.notifications) == bodies(expected["notifications"])


def test_minute_closes_when_next_minute_arrives():
    processor = StreamProcessor(60)
    first_minute = [m for m in MESSAGES[1:] if m["periodId"] == 1 and m["timeMin"] == 0]
    for m in [MESSAGES[0], *first_minute]:
        assert not [n for n in processor.process(m).notifications if n["messageType"] == "MinuteClosed"]
    nxt = next(m for m in MESSAGES[1:] if m["timeMin"] == 1)
    closed = [n for n in processor.process(nxt).notifications if n["messageType"] == "MinuteClosed"]
    assert [(n["periodId"], n["timeMin"]) for n in closed] == [(1, 0)]


def test_worker_end_to_end_ignores_other_messages_and_redelivery():
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, idle_seconds=75, clock=clock)
    worker.load()
    noise = [{"type": "MatchEvent", "version": 1}, {"type": "IntegrationProbe"}]
    run(worker, noise + MESSAGES)
    run(worker, MESSAGES[100:400])  # At-least-once redelivery changes nothing.
    finish(worker, clock)
    expected = pipeline.stream_outputs(MESSAGES, 60)
    for table in ("rawEvents", "keyEvents", "minuteStats"):
        assert canonical(repo.rows(table)) == canonical(expected[table]), table
    assert repo.outbox == bodies(expected["notifications"])


def test_restart_rebuilds_open_windows_from_sql():
    repo, clock = FakeRepository(), Clock()
    first = StreamWorker(repo, 60, clock=clock)
    first.load()
    run(first, MESSAGES[:1000])
    second = StreamWorker(repo, 60, clock=clock)  # New process: state comes only from the repository.
    second.load()
    run(second, MESSAGES, start=900)  # Resumes before the checkpoint; duplicates are skipped.
    finish(second, clock)
    expected = pipeline.stream_outputs(MESSAGES, 60)
    assert canonical(repo.rows("minuteStats")) == canonical(expected["minuteStats"])
    assert repo.outbox == bodies(expected["notifications"])


def test_failed_commit_discards_memory_and_keeps_checkpoint():
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    run(worker, MESSAGES[:500], batch=500)
    repo.fail = True
    try:
        run(worker, MESSAGES[500:600], batch=100)
    except ConnectionError:
        pass
    assert repo.checkpoints == {"0": 499}
    repo.fail = False
    worker.load()
    run(worker, MESSAGES, start=500)
    finish(worker, clock)
    expected = pipeline.stream_outputs(MESSAGES, 60)
    assert canonical(repo.rows("minuteStats")) == canonical(expected["minuteStats"])


def test_idle_close_then_late_event_joins_next_window():
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, idle_seconds=75, clock=clock)
    worker.load()
    minute0 = [m for m in MESSAGES[:200] if m["feed"] == "MA1" or m["timeMin"] == 0]
    run(worker, minute0[:-1])
    clock.now += 80
    worker.handle("0", [])  # Paused replay: the open window closes.
    run(worker, minute0[-1:])
    finish(worker, clock)
    stats = repo.rows("minuteStats")
    assert sum(r["events"] for r in stats) == len(minute0) - 1
    assert len({r["windowEnd"] for r in stats}) == 2
    closed = [b for b in repo.outbox.values() if b["messageType"] == "MinuteClosed"]
    assert Counter((b["periodId"], b["timeMin"]) for b in closed) == {(1, 0): 1}  # Same MessageId, sent once.


def test_purge_removes_one_run_and_ignores_its_late_deliveries():
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    other = [{**m, "matchId": "other-run"} for m in MESSAGES]
    run(worker, MESSAGES[:600] + other[:600])
    assert worker.purge(MESSAGES[0]["matchId"])[0] == [MESSAGES[0]["matchId"]]
    assert not worker.processor.open.get(MESSAGES[0]["matchId"])
    run(worker, MESSAGES[600:] + other[600:])  # In-flight deliveries of the purged run are dropped.
    finish(worker, clock)
    assert {r["matchId"] for t in ("matches", "rawEvents", "minuteStats") for r in repo.rows(t)} == {"other-run"}
    expected = pipeline.stream_outputs(other, 60)
    for table in ("rawEvents", "keyEvents", "minuteStats"):
        assert canonical(repo.rows(table)) == canonical(expected[table]), table
    assert repo.outbox == bodies(expected["notifications"])


def test_a_restored_seed_carries_on_as_if_the_run_had_never_stopped():
    """A run stopped at a point, exported and loaded under a new matchId, then fed only what
    follows the point (no MA1), writes the same rows and notifications as one uninterrupted run."""
    from local_stream.demo_seeds import RestoreRefused, export, restore
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    source, new = MESSAGES[0]["matchId"], "seeded-run"
    point = 900
    run(worker, MESSAGES[:point])
    clock.now += 1000
    worker.handle("0", [])  # the held run settles: its last window closes
    schema, seed = export(worker, repo, source)
    seed = json.loads(json.dumps(seed).replace(source, new))
    seed["canonicalEvents"] = [{"matchId": new, "seq": 2}]  # a canonical event past the seed's seq is refused
    with pytest.raises(RestoreRefused):
        restore(worker, repo, new, seed, 1, schema)
    seed["canonicalEvents"] = []
    max_seq = 0
    with pytest.raises(RestoreRefused):
        restore(worker, repo, new, seed, max_seq, "another-schema")
    restore(worker, repo, new, seed, max_seq, schema)
    with pytest.raises(RestoreRefused):
        restore(worker, repo, new, seed, max_seq, schema)  # known now
    moved = [{**m, "matchId": new} for m in MESSAGES]
    for m in moved:  # MatchEvent v2 bodies carry the matchId inside their event too
        if isinstance(m.get("event"), dict) and "match_id" in m["event"]:
            m["event"] = {**m["event"], "match_id": new}
    run(worker, moved[point:])
    finish(worker, clock)
    whole, clock2 = FakeRepository(), Clock()
    reference = StreamWorker(whole, 60, clock=clock2)
    reference.load()
    run(reference, moved[:point])
    clock2.now += 1000
    reference.handle("0", [])
    run(reference, moved[point:])
    finish(reference, clock2)
    for table in ("canonicalEvents", "rawEvents", "keyEvents", "minuteStats", "possessionSamples"):
        assert canonical([r for r in repo.rows(table) if r["matchId"] == new]) == canonical(whole.rows(table)), table
    assert repo.progress.get(new) == whole.progress.get(new)


def test_seed_routes_are_mounted_only_with_the_demo_setting(monkeypatch):
    """A production release (DEMO_SEEDS off) serves no export or restore; with it on, both answer."""
    import urllib.error
    import urllib.request
    from local_stream import admin

    repo = FakeRepository()
    worker = StreamWorker(repo, 60)
    worker.load()
    for setting, expected in (("0", 404), ("1", 200)):
        monkeypatch.setenv("DEMO_SEEDS", setting)
        server = admin.serve(worker, repo, port=0, routes=admin.demo_routes(worker, repo))
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            try:
                status = urllib.request.urlopen(base + "/admin/matches/export?match_id=m").status
            except urllib.error.HTTPError as error:
                status = error.code
            assert status in ((404,) if expected == 404 else (200, 503)), (setting, status)
        finally:
            server.shutdown()


def test_admin_api_purges_by_match_id_or_all():
    import urllib.error
    import urllib.request
    from local_stream import admin

    repo = FakeRepository()
    worker = StreamWorker(repo, 60)
    worker.load()
    run(worker, MESSAGES[:200])
    server = admin.serve(worker, repo, port=0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert json.load(urllib.request.urlopen(base + "/health"))["status"] == "ok"
        post = lambda path, body: urllib.request.urlopen(urllib.request.Request(
            base + path, json.dumps(body).encode(), {"Content-Type": "application/json"}))
        reply = json.load(post("/admin/matches/purge", {"match_id": MESSAGES[0]["matchId"]}))
        assert reply["match_ids"] == [MESSAGES[0]["matchId"]] and reply["purged"]["rawEvents"] > 0
        assert not repo.rows("rawEvents") and MESSAGES[0]["matchId"] in worker.purged
        assert json.load(post("/admin/matches/purge", {"match_id": "unknown-1"}))["purged"]["rawEvents"] == 0
        assert "unknown-1" in worker.purged  # Unknown match: zero counts, tombstone written.
        try:
            post("/admin/runs/purge", {"match_id": "old-run"})
            raise AssertionError("the removed run purge path answered")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        assert json.load(post("/admin/matches/purge", {"all": True}))["match_ids"] == []
        assert worker.cutoff is not None
        for bad in ({}, {"all": False}, {"match_id": "x", "all": True}, {"match_id": ""}, {"match_id": "x", "extra": 1}):
            try:
                post("/admin/matches/purge", bad)
                raise AssertionError(f"accepted {bad}")
            except urllib.error.HTTPError as exc:
                assert exc.code == 422
    finally:
        server.shutdown()


# MatchEvent v2 + POS (multi-match contract).
import v2_stream  # noqa: E402

V2 = v2_stream.build()
V2_ID = V2[0]["matchId"]


def committed_prefix_holds(repo, match_id):
    """Everything the watermark promises is committed: events ≤ w, their MA3 rows, POS up to V(w)."""
    watermark = repo.progress.get(match_id, (0, None))[0]
    events = {e["seq"]: e for e in repo.rows("canonicalEvents") if e["matchId"] == match_id}
    if not watermark:
        return True
    video = events[watermark]["videoSeconds"]
    sent = [m for m in V2 if m["matchId"] == match_id]
    want_ma3 = {m["id"] for m in sent if m.get("feed") == "MA3" and m["eventSeq"] <= watermark}
    want_pos = {m["sampleId"] for m in sent if m.get("feed") == "POS" and m["videoSeconds"] <= video}
    have_ma3 = {r["id"] for r in repo.rows("rawEvents") if r["matchId"] == match_id}
    have_pos = {r["sampleId"] for r in repo.rows("possessionSamples") if r["matchId"] == match_id}
    return set(range(1, watermark + 1)) <= set(events) and want_ma3 <= have_ma3 and want_pos <= have_pos


def test_v2_rows_watermark_and_status():
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    run(worker, V2[:1])
    assert repo.progress == {} and worker.matches[V2_ID].status == "scheduled"
    for i in range(1, 4000, 23):  # Uneven batches split events from their MA3 rows.
        run(worker, V2[i:i + 23], start=0, batch=23)
        assert committed_prefix_holds(repo, V2_ID)
    watermark, status = repo.progress[V2_ID]
    last = max(e["seq"] for e in repo.rows("canonicalEvents"))
    assert status == "live" and watermark in (last - 1, last)
    clock.now += 5
    worker.handle("0", [])  # A quiet spell completes the latest event.
    assert repo.progress[V2_ID][0] == last
    run(worker, V2[4000:], batch=97)
    assert committed_prefix_holds(repo, V2_ID)
    finish(worker, clock)
    expected = pipeline.stream_outputs(V2, 60)
    assert repo.progress[V2_ID] == (len(expected["canonicalEvents"]), "finished")
    for table in ("matchTeams", "matchPlayers", "canonicalEvents", "possessionSamples", "rawEvents", "keyEvents"):
        assert canonical(repo.rows(table)) == canonical(expected[table]), table
    team = next(r for r in repo.rows("matchTeams") if r["contestantId"] == "riverton")
    assert (team["position"], team["code"], team["primaryColour"]) == ("home", "RVR", "#001c68")
    match = repo.rows("matches")[0]
    assert (match["fixture"], match["sourceMatchId"]) == ("riverton-forgeham", "product-demo-match")


def test_lost_events_hold_the_watermark_before_the_gap(caplog):
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    events = [i for i, m in enumerate(V2) if m.get("type") == "MatchEvent"]
    lost = range(events[100], events[150])  # e.g. an Event Hubs emulator restart
    run(worker, [m for i, m in enumerate(V2[:events[300]]) if i not in lost])
    finish(worker, clock)
    assert repo.progress[V2_ID][0] == 100
    assert max(e["seq"] for e in repo.rows("canonicalEvents")) == 100
    assert "events were lost" in caplog.text


def test_malformed_messages_are_dropped_without_blocking_the_partition(caplog):
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    bad_ma1 = {**MESSAGES[0], "matchId": "bad-match", "contestant": []}  # No home/away teams.
    bad_ma3 = {k: v for k, v in MESSAGES[1].items() if k != "typeId"} | {"id": -1}
    no_id = {k: v for k, v in MESSAGES[1].items() if k != "id"}  # Malformed envelopes, too.
    no_seq = {"type": "MatchEvent", "version": 2, "matchId": MESSAGES[0]["matchId"]}
    list_id = {**MESSAGES[0], "matchId": ["bad-match"]}  # Unhashable: must not escape the drop policy.
    bad_again = {**MESSAGES[0], "contestant": []}  # A malformed MA1 for a match already running keeps its state.
    run(worker, [bad_ma1, list_id, MESSAGES[0], bad_again, bad_ma3, no_id, no_seq, *MESSAGES[1:]])
    finish(worker, clock)
    assert "bad-match" not in worker.matches and "Dropped a malformed MA1" in caplog.text
    assert MESSAGES[0]["matchId"] in worker.matches
    expected = pipeline.stream_outputs(MESSAGES, 60)
    for table in ("matches", "rawEvents", "keyEvents", "minuteStats"):
        assert canonical(repo.rows(table)) == canonical(expected[table]), table


def test_messages_need_a_stored_ma1_after_the_cutoff():
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    run(worker, V2[1:300])  # No MA1: nothing is created.
    assert not any(repo.rows(t) for t in repo.KEYS)
    worker.purge()  # Purge all: cut-off now; this MA1 is stamped a minute before kickoff in 2026.
    worker.cutoff = pipeline.parse_time("2026-10-20T15:00:00Z")
    run(worker, V2[:300])
    assert not repo.rows("matches") and not repo.rows("canonicalEvents")
    later = v2_stream.build("0badc0de", kickoff=pipeline.parse_time("2026-10-20T15:02:00Z"))
    run(worker, later[:300])
    assert {r["matchId"] for r in repo.rows("canonicalEvents")} == {later[0]["matchId"]}


def test_purge_survives_restart_and_redelivery():
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    other = v2_stream.build("feedf00d")
    run(worker, V2[:2000] + other[:2000])
    ids, counts = worker.purge(V2_ID)
    assert ids == [V2_ID] and counts["canonicalEvents"] > 0
    restarted = StreamWorker(repo, 60, clock=clock)
    restarted.load()
    run(restarted, V2)  # Redelivery from the start, MA1 included.
    finish(restarted, clock)
    assert all(r["matchId"] != V2_ID for t in repo.KEYS for r in repo.rows(t))
    assert V2_ID not in repo.progress and V2_ID not in repo.closed
    assert any(r["matchId"] == other[0]["matchId"] for r in repo.rows("canonicalEvents"))


def test_interleaved_matches_stay_isolated():
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    a = v2_stream.build("aaaa0001")
    b = v2_stream.build("bbbb0002", kickoff=v2_stream.KICKOFF + timedelta(seconds=7.3))
    run(worker, v2_stream.interleave(a, b), batch=61)
    finish(worker, clock)
    for stream in (a, b):
        mid, expected = stream[0]["matchId"], pipeline.stream_outputs(stream, 60)
        for table in ("canonicalEvents", "possessionSamples", "rawEvents", "keyEvents", "matchPlayers"):
            assert canonical(r for r in repo.rows(table) if r["matchId"] == mid) == canonical(expected[table]), table
        assert repo.progress[mid] == (len(expected["canonicalEvents"]), "finished")


def test_failed_load_reconnects_before_the_retry():
    repo, calls = FakeRepository(), []
    load, repo.load = repo.load, lambda: (_ for _ in ()).throw(ConnectionError("connection reset"))
    repo.rollback = lambda: calls.append("rollback")
    worker = StreamWorker(repo, 60)
    try:
        worker.load()
        raise AssertionError("load succeeded")
    except ConnectionError:
        pass
    repo.load = load
    assert calls == ["rollback"] and worker.load() == {}


def test_admin_api_alone_needs_its_token():
    """ETL_ROLE=admin on Azure: the purge without a worker, behind a bearer token."""
    import urllib.error
    import urllib.request
    from local_stream import admin

    repo = FakeRepository()
    server = admin.serve(admin.SqlPurger(), repo, port=0, token="t0ken")
    url = f"http://127.0.0.1:{server.server_address[1]}/admin/matches/purge"
    post = lambda headers: urllib.request.urlopen(urllib.request.Request(
        url, json.dumps({"match_id": "m-1"}).encode(), {"Content-Type": "application/json", **headers}))
    try:
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            try:
                post(headers)
                raise AssertionError("purged without the token")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
        assert json.load(post({"Authorization": "Bearer t0ken"}))["match_ids"] == ["m-1"] and repo.purged == {"m-1"}
    finally:
        server.shutdown()
    import os
    from unittest import mock
    with mock.patch.dict(os.environ, {"ETL_ADMIN_TOKEN": ""}):
        try:
            admin.main()
            raise AssertionError("served without a token")
        except SystemExit:
            pass


class FakeHub:
    """Event Hubs client double: one partition; receive_batch delivers `events` then blocks until close."""

    def __init__(self, last, events=()):
        import threading
        self.last, self.events, self.closed, self.started = last, list(events), threading.Event(), []

    def get_partition_ids(self):
        return ["0"]

    def get_partition_properties(self, partition):
        return {"last_enqueued_sequence_number": self.last}

    def receive_batch(self, on_event_batch, starting_position, **options):
        self.started.append(dict(starting_position))
        if self.events:
            on_event_batch(type("Context", (), {"partition_id": "0"})(), self.events)
        self.closed.wait(5)

    def close(self):
        self.closed.set()


class HubEvent:
    def __init__(self, seq, body):
        self.sequence_number, self.body = seq, body

    def body_as_str(self):
        return self.body


def test_a_hub_reset_while_connected_reconnects_from_latest(caplog):
    """The emulator restarted under a live consumer: the partition's last sequence number drops
    below the consumer's position. It logs, reconnects, and the stale checkpoint is not reused."""
    import threading
    from datetime import datetime
    from local_stream.adapters import consume_once
    repo = FakeRepository()
    repo.checkpoints = {"0": 40}
    worker = StreamWorker(repo, 60)
    hub = FakeHub(last=50, events=[HubEvent(50, json.dumps({"type": "IntegrationProbe"}))])
    done = threading.Thread(target=consume_once, args=(worker, hub, 0))
    done.start()
    while not hub.started:
        pass
    assert hub.started[0] == {"0": 40}
    hub.last = 3  # Restarted: new sequence numbers from 0.
    done.join(5)
    assert not done.is_alive() and hub.closed.is_set()
    assert "the hub was reset" in caplog.text
    # The stale checkpoint is forgotten: once the new hub passes 40 it must not skip events 0–40.
    assert "0" not in repo.checkpoints
    repo.checkpoints["0"] = 40  # As if stored before the reset: the reconnect also detects it.
    again = FakeHub(last=3)
    threading.Thread(target=consume_once, args=(worker, again, 3600), daemon=True).start()
    while not again.started:
        pass
    assert isinstance(again.started[0]["0"], datetime) and "0" not in repo.checkpoints
    again.close()
