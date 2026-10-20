"""Service Bus settling, narrative messages and routing, with fake receiver/sender objects."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from narrative_engine.agents.fake import FakeAgents
from narrative_engine.match_data.fixture import FixtureMatchData
from narrative_engine.store.memory import MemoryStore
from narrative_engine.service import Router
from narrative_engine.transport.files import MemorySink, narrative_doc, read_notifications
from azure.servicebus.exceptions import MessageLockLostError

from narrative_engine.transport.servicebus import ServiceBusPublisher, settle

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
        await settle(receiver, message({"matchId": "b"}), ok, fixed_type="PresenceChanged")
        await settle(receiver, message({"matchId": "c"}), fails)
        await settle(receiver, message(b"not json"), ok)
    asyncio.run(go())
    assert seen == [("a", "MinuteClosed"), ("b", "PresenceChanged")]
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
    publisher.opened = True
    asyncio.run(publisher.publish(narrative))
    out = sent[0]
    assert out.message_id == narrative.id and out.content_type == "application/json"
    assert out.application_properties == {"userType": narrative.userType, "matchId": narrative.matchId}
    assert json.loads(str(out)) == narrative_doc(narrative)


async def _record(sent, m):
    sent.append(m)


def test_router_runs_one_engine_per_match_and_filters():
    store = MemoryStore()
    router = Router(DATA, FakeAgents(), store, MemorySink(store), match_ids={"match-a", "match-b"})
    bodies = [b for b, _ in read_notifications(NOTIFICATIONS)][:30]

    async def go():
        for match_id in ("match-a", "match-b", "someone-else"):
            for body in bodies:
                await router.handle({**body, "matchId": match_id}, body["messageType"])
        await router.idle()  # buckets are chosen when a step is queued, so let both matches catch up first
        await router.handle({"matchId": "match-a", "activeUserTypes": {"home:casual": 1},
                             "sentAt": "2099-01-01T00:00:00Z"}, "PresenceChanged")
        await router.handle({"matchId": "match-a", "messageType": "SomethingNew"})
        await router.idle()
    asyncio.run(go())
    assert set(router.engines) == {"match-a", "match-b"}
    assert router.engines["match-a"].active_buckets() == ["home:casual"]
    a, b = (asyncio.run(store.narratives(m, "neutral:casual")) for m in ("match-a", "match-b"))
    assert [n.stepId.split(":", 1)[1] for n in a] == [n.stepId.split(":", 1)[1] for n in b] and a
