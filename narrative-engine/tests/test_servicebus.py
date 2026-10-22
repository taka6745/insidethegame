"""Service Bus settling, narrative messages and routing, with fake receiver/sender objects."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from narrative_engine.devtools.fake_agents import FakeAgents
from narrative_engine.core.config import Settings
from narrative_engine.core.gate import ModelGate
from narrative_engine.devtools.fixture_data import FixtureMatchData
from narrative_engine.store.memory import MemoryStore
import functools

from narrative_engine import service
from narrative_engine.devtools.targets import StaticTargets, default_targets
from narrative_engine.transport.files import MemorySink, narrative_doc, read_notifications
from azure.servicebus.exceptions import MessageLockLostError

from narrative_engine.transport.servicebus import ServiceBusPublisher, settle

Router = functools.partial(service.Router, targets=StaticTargets(default_targets()))  # tests: Luke's 12 buckets

FIXTURES = Path(__file__).parent / "fixtures"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
DATA = FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS)


def message(body, props=None):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return SimpleNamespace(body=iter([raw]), application_properties=props, message_id="m1", delivery_count=1)


class FakeReceiver:
    def __init__(self, lock_lost=False):
        self.settled, self.lock_lost = [], lock_lost

    async def complete_message(self, m):
        if self.lock_lost:
            raise MessageLockLostError(message="lock expired")
        self.settled.append("complete")

    async def abandon_message(self, m):
        self.settled.append("abandon")

    async def dead_letter_message(self, m, reason, error_description):
        self.settled.append(f"dead-letter:{reason}")


def test_settle_completes_abandons_or_dead_letters():
    seen = []

    async def ok(body, kind):
        seen.append((body["matchId"], kind))

    async def fails(body, kind):
        raise RuntimeError("LLM down")

    receiver = FakeReceiver()

    async def go():
        await settle(receiver, message({"matchId": "a"}, {b"notificationType": b"MinuteClosed"}), ok)
        await settle(receiver, message({"matchId": "b"}), ok)  # no notificationType: the body's messageType
        await settle(receiver, message({"matchId": "c"}), fails)
        await settle(receiver, message(b"not json"), ok)
    asyncio.run(go())
    assert seen == [("a", "MinuteClosed"), ("b", None)]
    assert receiver.settled == ["complete", "complete", "abandon", "dead-letter:unreadable"]
    lost = FakeReceiver(lock_lost=True)
    asyncio.run(settle(lost, message({"matchId": "d"}), ok))  # logged, not raised: Service Bus redelivers
    assert seen[-1] == ("d", None) and lost.settled == []


def test_publisher_sends_the_narrative_document_with_its_id_and_bucket():
    store = MemoryStore()
    router = Router(DATA, FakeAgents(), store, MemorySink(store))
    first_goal = next(i for i, (b, _) in enumerate(read_notifications(NOTIFICATIONS)) if b["messageType"] == "KeyEventDetected")

    async def go():
        for body, _ in read_notifications(NOTIFICATIONS)[:first_goal + 1]:
            await router.handle(body)
        await router.idle()
    asyncio.run(go())
    narrative = router.publisher.published[-1]

    sent = []
    publisher = ServiceBusPublisher.__new__(ServiceBusPublisher)
    publisher.sender = SimpleNamespace(send_messages=lambda m: _record(sent, m))
    publisher.lock = asyncio.Lock()
    asyncio.run(publisher.publish(narrative))
    out = sent[0]
    assert out.message_id == narrative.id and out.content_type == "application/json"
    assert out.application_properties == {"userType": narrative.userType, "matchId": narrative.matchId,
                                          "kind": "bucket"}
    assert json.loads(str(out)) == narrative_doc(narrative)


async def _record(sent, m):
    sent.append(m)


def test_publisher_sends_a_follow_clip_with_its_id_on_the_same_topic():
    clip = {"type": "FollowClip", "id": "clip:m:topic:00000000000000c1:7", "matchId": "m",
            "topicId": "topic:00000000000000c1", "eventId": 7, "eventSeq": 40, "stepId": "m:sub:topic:00000000000000c1:key:7",
            "decision": {"clip": True}}
    sent = []
    publisher = ServiceBusPublisher.__new__(ServiceBusPublisher)
    publisher.sender = SimpleNamespace(send_messages=lambda m: _record(sent, m))
    publisher.lock = asyncio.Lock()
    asyncio.run(publisher.publish_clip(clip))
    assert sent[0].message_id == clip["id"] and json.loads(str(sent[0])) == clip
    assert sent[0].application_properties == {"matchId": "m", "kind": "clip"}


def test_a_failed_send_replaces_the_sender():
    sent, made = [], []

    class Sender:
        def __init__(self, broken):
            self.broken, self.closed = broken, False

        async def send_messages(self, m):
            if self.broken:
                raise AttributeError("'NoneType' object has no attribute 'create_sender_link'")
            sent.append(m)

        async def close(self):
            self.closed = True

    publisher = ServiceBusPublisher.__new__(ServiceBusPublisher)
    publisher.topic, publisher.lock = "narratives", asyncio.Lock()
    publisher.client = SimpleNamespace(get_topic_sender=lambda topic: made.append(Sender(not made)) or made[-1])
    publisher.sender = None
    narrative = SimpleNamespace(id="n1", userType="home:casual", matchId="m", kind="bucket")

    async def go():
        import narrative_engine.transport.servicebus as sb
        original, sb.narrative_doc = sb.narrative_doc, lambda n: {"id": n.id}
        try:
            try:
                await publisher.publish(narrative)
            except AttributeError:
                pass
            await publisher.publish(narrative)
        finally:
            sb.narrative_doc = original
    asyncio.run(go())
    assert len(made) == 2 and made[0].closed and len(sent) == 1


class Matches:
    """DATA addressed by run-scoped matchIds, each with its own MA1 time (`sent`: matchId -> ISO time)."""

    def __init__(self, sent=None, periods=None):
        self.sent, self.periods = sent or {}, periods

    def __getattr__(self, name):
        return getattr(DATA, name)

    async def match_info(self, match_id):
        from dataclasses import replace
        return replace(await DATA.match_info(match_id), matchId=match_id, periods=self.periods,
                       timeStamp=self.sent.get(match_id, "2026-10-20T09:00:00Z"))


BODIES = [b for b, _ in read_notifications(NOTIFICATIONS)]
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)


async def feed(router, match_id, bodies):
    for body in bodies:
        await router.handle({**body, "matchId": match_id}, body["messageType"])


async def feed_and_wait(router, match_id, bodies):
    await feed(router, match_id, bodies)
    await router.idle()


def summarised(store, match_id):
    return asyncio.run(store.get_checkpoint(match_id))["lastSummarised"]


def test_two_concurrent_matches_each_get_blocks_and_narratives():
    store = MemoryStore()
    router = Router(Matches(), FakeAgents(delay=0.001), store, MemorySink(store))

    async def go():
        await asyncio.gather(*(feed(router, m, BODIES[:40]) for m in ("chelsea-united-aaaa1111", "arsenal-spurs-bbbb2222")))
        await router.idle()
        await router.handle({"matchId": "chelsea-united-aaaa1111", "messageType": "SomethingNew"})
    asyncio.run(go())
    assert set(router.engines) == {"chelsea-united-aaaa1111", "arsenal-spurs-bbbb2222"}
    a, b = (asyncio.run(store.narratives(m, "neutral:casual")) for m in router.engines)
    assert a and [n.stepId.split(":", 1)[1] for n in a] == [n.stepId.split(":", 1)[1] for n in b]
    for match_id in router.engines:
        blocks = asyncio.run(store.all_blocks(match_id))
        assert blocks and {x.matchId for x in blocks} == {match_id} and {x.tier for x in blocks} >= {"minute"}


def test_with_a_model_limit_of_two_three_matches_all_advance_their_minute_summaries():
    store, agents = MemoryStore(), FakeAgents(author_delay=0.01, delay=0.002)
    router = Router(Matches(), agents, store, MemorySink(store), Settings(model_concurrency=2))
    matches = [f"match-{i}-0000000{i}" for i in range(3)]
    last = [b for b in BODIES[:40] if b["messageType"] == "MinuteClosed"][-1]

    async def go():
        await asyncio.gather(*(feed(router, m, BODIES[:40]) for m in matches))
        await router.idle()
    asyncio.run(go())
    assert agents.max_in_flight == 2
    assert all(summarised(store, m) == f"{last['periodId']}-{last['timeMin']:03d}" for m in matches)
    assert all(asyncio.run(store.narratives(m)) for m in matches)


def test_the_model_gate_serves_summaries_first_then_the_match_served_least_recently():
    gate, order = ModelGate(1), []

    async def call(match_id, kind):
        async with gate.slot(match_id, kind):
            order.append((match_id, kind))
            await asyncio.sleep(0)

    async def go():
        async with gate.slot("a", "author"):  # holds the only slot while the others queue
            tasks = [asyncio.create_task(call(m, k)) for m, k in
                     [("a", "author"), ("a", "author"), ("b", "summary"), ("c", "author"), ("a", "summary")]]
            await asyncio.sleep(0)
        await asyncio.gather(*tasks)
    asyncio.run(go())
    assert order == [("b", "summary"), ("a", "summary"), ("c", "author"), ("a", "author"), ("a", "author")]
    assert gate.running == 0 and gate.waiting == []


def test_purging_one_match_leaves_the_others_and_a_restart_does_not_recreate_it():
    store = MemoryStore()
    router = Router(Matches(), FakeAgents(), store, MemorySink(store))

    async def go():
        await feed(router, "match-a-aaaa1111", BODIES[:20])
        await feed(router, "match-b-bbbb2222", BODIES[:20])
        await router.idle()
        b_before = len(await store.narratives("match-b-bbbb2222"))
        result = await router.purge("match-a-aaaa1111")
        assert result["match_ids"] == ["match-a-aaaa1111"] and result["purged"]["checkpoints"] == 1
        assert result["purged"]["narratives"] > 0 and result["purged"]["contextBlocks"] > 0
        assert "match-a-aaaa1111" not in router.engines and "match-b-bbbb2222" in router.engines
        assert len(await store.narratives("match-b-bbbb2222")) == b_before

        restarted = Router(Matches(), FakeAgents(), store, MemorySink(store))
        await restarted.start()
        assert set(restarted.engines) == {"match-b-bbbb2222"}
        await feed(restarted, "match-a-aaaa1111", BODIES[20:])  # late notifications of the purged match
        await feed(restarted, "match-b-bbbb2222", BODIES[20:])
        await restarted.idle()
        assert await store.get_checkpoint("match-a-aaaa1111") is None and not await store.narratives("match-a-aaaa1111")
        assert len(await store.narratives("match-b-bbbb2222")) > b_before
        assert (await restarted.purge("never-seen-00000000"))["purged"] == \
            {"checkpoints": 0, "contextBlocks": 0, "narratives": 0, "analyses": 0, "storylines": 0,
             "subscriptionDecisions": 0, "subscriptionNarratives": 0}
    asyncio.run(go())


def test_purge_all_drops_every_known_match_and_any_whose_ma1_predates_the_cut_off():
    store = MemoryStore()
    data = Matches({"old-unseen-cccc3333": "2026-10-20T09:59:00Z", "new-dddd4444": "2026-10-20T10:01:00Z"})
    router = Router(data, FakeAgents(), store, MemorySink(store), now=lambda: NOW)

    async def go():
        await feed(router, "old-aaaa1111", BODIES[:10])
        await router.idle()
        result = await router.purge(everything=True)
        assert result["match_ids"] == ["old-aaaa1111"] and await store.tombstones() == ({"old-aaaa1111"}, NOW.isoformat())
        restarted = Router(data, FakeAgents(), store, MemorySink(store))
        await restarted.start()
        for match_id in ("old-aaaa1111", "old-unseen-cccc3333", "new-dddd4444"):
            await feed(restarted, match_id, BODIES[:10])
        await restarted.idle()
        assert set(restarted.engines) == {"new-dddd4444"}
        assert await store.match_ids() == ["new-dddd4444"] and "old-unseen-cccc3333" in restarted.purged
    asyncio.run(go())


def test_the_match_ends_with_the_final_period_from_its_ma1():
    store = MemoryStore()
    router = Router(Matches(periods=1), FakeAgents(), store, MemorySink(store))
    asyncio.run(feed_and_wait(router, "one-half-aaaa1111", BODIES))
    checkpoint = asyncio.run(store.get_checkpoint("one-half-aaaa1111"))
    assert checkpoint["status"] == "complete" and "fullTime:1" in checkpoint["done"]
    blocks = asyncio.run(store.active_blocks("one-half-aaaa1111"))
    assert blocks[0].tier == "half" and blocks[0].coversFrom.periodId == 1
    asyncio.run(router.poll_once())
    assert router.engines == {}  # a finished match is let go


def test_narratives_carry_the_event_seq_of_their_data():
    class WithSeq(Matches):
        async def event_seq_of(self, match_id, event_id):  # a key event step reads up to its own row
            return event_id * 10

    store = MemoryStore()
    router = Router(WithSeq(), FakeAgents(), store, MemorySink(store))
    first_goal = next(i for i, b in enumerate(BODIES) if b["messageType"] == "KeyEventDetected")
    asyncio.run(feed_and_wait(router, "m-aaaa1111", BODIES[:first_goal + 1]))
    goal = BODIES[first_goal]
    narrative = asyncio.run(store.narratives("m-aaaa1111", "home:casual"))[-1]
    assert narrative.eventSeq == goal["id"] * 10
    assert router.publisher.published[-1].eventSeq == narrative.eventSeq


def test_service_app_serves_health_purge_and_graphql():
    import httpx
    from narrative_engine.api import NarrativeApi
    from narrative_engine.service import service_app

    store = MemoryStore()
    router = Router(DATA, FakeAgents(), store, MemorySink(store))
    app = service_app(NarrativeApi(store), router)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as client:
            assert (await client.get("/health")).json() == {"status": "ok"}
            for bad in ({}, {"match_id": "m", "all": True}, {"all": False}, {"match_id": ""}, {"all": "yes"}, []):
                assert (await client.post("/admin/matches/purge", json=bad)).status_code == 422, bad
            assert (await client.get("/admin/matches/purge")).status_code == 405
            response = await client.post("/admin/matches/purge", json={"match_id": "demo-aaaa1111"})
            assert response.json() == {"match_ids": ["demo-aaaa1111"],
                                       "purged": {"checkpoints": 0, "contextBlocks": 0, "narratives": 0, "analyses": 0, "storylines": 0,
                                                  "subscriptionDecisions": 0, "subscriptionNarratives": 0}}
            assert "demo-aaaa1111" in router.purged
            assert (await client.post("/admin/matches/purge", json={"all": True})).status_code == 200
            graphql = await client.post("/graphql", json={"query": "{ contextBlocks(matchId: \"m\") { id tier } }"})
            assert graphql.json() == {"data": {"contextBlocks": []}}
    asyncio.run(go())


def test_purge_needs_the_bearer_token_when_configured():
    import httpx
    from narrative_engine.api import NarrativeApi
    from narrative_engine.service import service_app

    store = MemoryStore()
    router = Router(DATA, FakeAgents(), store, MemorySink(store))
    app = service_app(NarrativeApi(store), router, admin_token="s3cret")

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as client:
            body = {"match_id": "demo-aaaa1111"}
            for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic s3cret"}):
                assert (await client.post("/admin/matches/purge", json=body, headers=headers)).status_code == 401
            assert not router.purged and (await client.get("/health")).status_code == 200
            ok = await client.post("/admin/matches/purge", json=body, headers={"Authorization": "Bearer s3cret"})
            assert ok.status_code == 200 and "demo-aaaa1111" in router.purged
    asyncio.run(go())


def test_without_the_user_backend_authoring_pauses_and_health_is_unhealthy():
    import httpx
    from narrative_engine.agents.prompt_source import HttpPromptSource
    from narrative_engine.api import NarrativeApi
    from narrative_engine.audience.targets import HttpTargetSource
    from narrative_engine.service import service_app

    down = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    store, agents = MemoryStore(), FakeAgents()
    router = Router(Matches(), agents, store, MemorySink(store), Settings(retry_seconds=60),
                    targets=HttpTargetSource("http://backend", down), prompts=HttpPromptSource("http://backend", down))
    app = service_app(NarrativeApi(store), router)

    async def go():
        await feed(router, "m-aaaa1111", BODIES[:20])
        await asyncio.sleep(0.05)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as client:
            health = await client.get("/health")
        await router.stop("m-aaaa1111")
        return health
    health = asyncio.run(go())
    assert health.status_code == 503 and health.json()["status"] == "unhealthy" and health.json()["problems"]
    assert agents.calls == [] and not asyncio.run(store.narratives("m-aaaa1111"))  # paused: no fallback buckets or prompts
    checkpoint = asyncio.run(store.get_checkpoint("m-aaaa1111"))
    assert checkpoint["targets"] is None and checkpoint["lastSummarised"] is None


def test_the_listener_reconnects_in_process_after_losing_the_broker():
    """Connection 1 fails at once, 2 delivers a message then drops, 3 delivers the next."""
    from azure.servicebus.exceptions import ServiceBusConnectionError

    from narrative_engine.transport.servicebus import SubscriptionListener

    batches = {1: [ServiceBusConnectionError(message="refused")],
               2: [[message({"matchId": "a"})], ServiceBusConnectionError(message="link detached")],
               3: [[message({"matchId": "b"})]]}
    seen, receivers = [], []

    class Receiver(FakeReceiver):
        def __init__(self, script):
            super().__init__()
            self.script, self.closed = script, False

        async def receive_messages(self, max_message_count, max_wait_time):
            if not self.script:
                await asyncio.sleep(3600)
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            self.closed = True

    class Client:
        def __init__(self, connection):
            self.connection = connection

        def get_subscription_receiver(self, topic, subscription):
            receivers.append(Receiver(batches[self.connection]))
            return receivers[-1]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

    async def handle(body, kind):
        seen.append(body["matchId"])

    class Renewer:
        def __init__(self, max_lock_renewal_duration):
            pass

        def register(self, receiver, message):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

    listener = SubscriptionListener("conn", "match-notifications", "narrative-engine", handle, retry_seconds=0.01,
                                    client_factory=lambda conn: Client(listener.connections), lock_renewer=Renewer)

    async def go():
        task = asyncio.create_task(listener.run())
        while len(seen) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(asyncio.wait_for(go(), 5))
    assert seen == ["a", "b"] and listener.connections == 3
    assert [r.settled for r in receivers] == [[], ["complete"], ["complete"]]
    assert all(r.closed for r in receivers)


def test_a_busy_or_unreachable_broker_is_a_pause_not_a_fault():
    from azure.servicebus.exceptions import ServiceBusServerBusyError
    from narrative_engine.core.models import BrokerUnavailable

    class Busy:
        async def send_messages(self, m):
            raise ServiceBusServerBusyError(message="namespace is being throttled")

        async def close(self):
            pass

    publisher = ServiceBusPublisher.__new__(ServiceBusPublisher)
    publisher.topic, publisher.lock, publisher.sender = "narratives", asyncio.Lock(), None
    publisher.client = SimpleNamespace(get_topic_sender=lambda topic: Busy())
    narrative = SimpleNamespace(id="n1", userType="home:casual", matchId="m", kind="bucket")

    async def go():
        import narrative_engine.transport.servicebus as sb
        original, sb.narrative_doc = sb.narrative_doc, lambda n: {"id": n.id}
        try:
            await publisher.publish(narrative)
        finally:
            sb.narrative_doc = original

    try:
        asyncio.run(go())
    except BrokerUnavailable as error:
        assert isinstance(error.__cause__, ServiceBusServerBusyError) and publisher.sender is None
    else:
        raise AssertionError("expected BrokerUnavailable")


def test_a_seed_restores_under_a_new_match_id_and_the_match_carries_on_from_it():
    """PLAN.md §10.6: export one match, load it as another; nothing is redone, later minutes continue."""
    import httpx
    from narrative_engine.api import NarrativeApi
    from narrative_engine.demo.seeds import SEED_STORES, seed_app
    from narrative_engine.service import service_app

    store = MemoryStore()
    data = Matches({"rec-aaaa1111": "2026-10-20T09:59:00Z", "new-bbbb2222": "2026-10-20T09:59:00Z"})
    router = Router(data, FakeAgents(), store, MemorySink(store), now=lambda: NOW)
    app = seed_app(service_app(NarrativeApi(store), router), router)

    async def go():
        await feed_and_wait(router, "rec-aaaa1111", BODIES[:40])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as client:
            exported = (await client.post("/admin/matches/export", json={"match_id": "rec-aaaa1111"})).json()
            seed, schema = exported["containers"], exported["schema"]
            assert set(seed) == set(SEED_STORES) and seed["narratives"]
            await router.purge(everything=True)  # a purge-all after the recording: its cut-off is later than its MA1
            moved = json.loads(json.dumps(seed).replace("rec-aaaa1111", "new-bbbb2222"))
            other = json.loads(json.dumps(seed).replace("rec-aaaa1111", "other-cccc3333"))
            seq = max(d["eventSeq"] or 0 for d in seed["narratives"] + seed["analyses"])

            async def restore(containers, max_seq=seq, schema=schema):
                return await client.post("/admin/matches/restore", json={
                    "match_id": "new-bbbb2222", "max_seq": max_seq, "schema": schema, "containers": containers})
            assert (await restore(other)).status_code == 409  # documents of another match
            assert (await restore(moved, seq - 1)).status_code == 409  # narratives past the seed's seq
            assert (await restore(moved, schema="other")).status_code == 409  # another engine schema
            assert (await restore(moved)).status_code == 200
            assert (await restore(moved)).status_code == 409  # known now
            again = (await client.post("/admin/matches/export", json={"match_id": "new-bbbb2222"})).json()["containers"]
            assert again == moved
        before = {n.id for n in await store.narratives("new-bbbb2222")}
        blocks = {b.id for b in await store.all_blocks("new-bbbb2222")}
        await feed_and_wait(router, "new-bbbb2222", BODIES[:60])  # redeliveries, then what follows the seed
        assert before < {n.id for n in await store.narratives("new-bbbb2222")}
        assert blocks < {b.id for b in await store.all_blocks("new-bbbb2222")}
        assert "new-bbbb2222" not in router.purged
        await router.purge("new-bbbb2222")  # a restored match purges like any other
        from narrative_engine.demo.seeds import export
        assert not any((await export(store, "new-bbbb2222")).values())
    asyncio.run(go())


def test_every_restored_document_is_bounded_by_the_seeds_seq():
    from narrative_engine.demo.seeds import past_seq
    seed = {"checkpoints": [{"closedThrough": "1-019", "pending": [{"seq": 40}]}],
            "contextBlocks": [{"coversTo": {"periodId": 1, "timeMin": 19}}],
            "narratives": [{"eventSeq": 50}], "analyses": [{"id": "a1", "eventSeq": 50}],
            "storylines": [{"openedBy": "a1", "lastAnalysisId": "a1", "beats": [{"analysisId": "a1"}]}]}
    assert past_seq(seed, 50) is None
    assert past_seq({**seed, "analyses": [{"id": "a1", "eventSeq": 51}]}, 50) == "analyses"
    assert past_seq({**seed, "checkpoints": [{"closedThrough": "1-019", "pending": [{"seq": 51}]}]}, 50) == "queued steps"
    assert past_seq({**seed, "storylines": [{"openedBy": "a2"}]}, 50) == "storylines"
    assert past_seq({**seed, "contextBlocks": [{"coversTo": {"periodId": 1, "timeMin": 20}}]}, 50) == "summaries"


def test_seed_batches_stay_within_cosmos_operation_and_size_limits():
    from narrative_engine.demo import seeds
    small = [{"id": str(i)} for i in range(250)]
    assert [len(b) for b in seeds.batches(small)] == [100, 100, 50]
    large = [{"id": str(i), "text": "x" * 600_000} for i in range(5)]
    assert [len(b) for b in seeds.batches(large)] == [2, 2, 1]
    assert [d for b in seeds.batches(large) for d in b] == large


def test_without_the_demo_setting_the_service_has_no_seed_routes():
    """A production release (DEMO_SEEDS off) serves no export or restore; they fall through to GraphQL."""
    import httpx
    from narrative_engine.api import NarrativeApi
    from narrative_engine.service import service_app

    store = MemoryStore()
    router = Router(Matches({}), FakeAgents(), store, MemorySink(store), now=lambda: NOW)
    app = service_app(NarrativeApi(store), router)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as client:
            for path in ("/admin/matches/export", "/admin/matches/restore"):
                response = await client.post(path, json={"match_id": "m"})
                assert response.status_code != 200 or "containers" not in response.text
                assert "restored" not in response.text
    asyncio.run(go())
