"""Broker receipt, not producer timing, owns committed custom values."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from backend.adapters.match_brokers import settle_bucket_message
from backend.adapters.broker_data import BrokerQuestionData
from backend.models.broker import MatchDelivery, BucketDelivery
from backend.models.rules import Rule
from backend.services.broker_runtime import BrokerRuntime
from backend.services.question_snapshot import build_snapshot
from backend.repositories.broker_inbox import NarrativeInbox
from test_lab_service import setup


def envelope(payload, event):
    metadata = payload.model_copy(update={'events': []})
    return MatchDelivery(type='MatchEvent', version=1, snapshot=metadata, event=event)


def bucket(payload, revision=1):
    return BucketDelivery(type='BucketNarratives', version=1, snapshot=payload.snapshot,
                          items=[], events=[], audience_revision=revision)


def test_event_receipt_commits_once_and_ignores_previous_run():
    async def run():
        lab, repo = await setup()
        await lab.register(Rule(match_id=lab.source.match_id), 'All actions')
        runtime = BrokerRuntime(lab, None, None)
        payload = build_snapshot(lab.source, lab.run_id, 1)
        delivery = envelope(payload, payload.events[-1])
        await runtime.accept_event(delivery)
        await runtime.accept_event(delivery)
        assert lab.position == repo.run['position'] == 1
        assert lab.engine.calculations[0].value == 1
        await lab.reset()
        await runtime.accept_event(delivery)
        assert lab.position == 0
    asyncio.run(run())


def test_gaps_and_wrong_events_cannot_advance_index():
    async def run():
        lab, _ = await setup()
        runtime = BrokerRuntime(lab, None, None)
        payload = build_snapshot(lab.source, lab.run_id, 2)
        with pytest.raises(ValueError, match='gap'):
            await runtime.accept_event(envelope(payload, payload.events[-1]))
        payload = build_snapshot(lab.source, lab.run_id, 1)
        with pytest.raises(ValueError, match='recording'):
            await runtime.accept_event(envelope(payload, lab.source.events[1]))
        assert lab.position == 0
    asyncio.run(run())


def test_publish_waits_for_consumer_and_database_failure_can_retry():
    async def run():
        lab, repo = await setup()
        transport = SimpleNamespace(publish=AsyncMock())
        runtime = BrokerRuntime(lab, transport, None, timeout=.5)
        lab.broker = runtime
        pending = asyncio.create_task(lab.advance())
        await asyncio.sleep(.01)
        assert lab.position == 0 and not pending.done()
        payload, event = transport.publish.call_args.args
        repo.fail_progress = True
        with pytest.raises(OSError):
            await runtime.accept_event(envelope(payload, event))
        assert lab.position == 0
        repo.fail_progress = False
        await runtime.accept_event(envelope(payload, event))
        assert await pending
        assert lab.position == 1
    asyncio.run(run())


def test_durable_narrative_acceptance_precedes_ack_and_retries_failure(monkeypatch):
    async def run():
        lab, _ = await setup()
        delivery = bucket(build_snapshot(lab.source, lab.run_id, 0))
        receiver = AsyncMock()
        accept = AsyncMock(side_effect=[*[OSError('db unavailable') for _ in range(12)], None])
        monkeypatch.setattr('backend.adapters.match_brokers.asyncio.sleep', AsyncMock())
        await settle_bucket_message(receiver, delivery.model_dump_json(), accept)
        receiver.abandon_message.assert_not_awaited()
        receiver.complete_message.assert_awaited_once()
        assert accept.await_count == 13
        await settle_bucket_message(receiver, '{bad', accept)
        receiver.dead_letter_message.assert_awaited_once()
    asyncio.run(run())


def test_narrative_inbox_revision_is_monotonic_and_survives_restart(store):
    store.initialize()
    inbox = NarrativeInbox(store)
    inbox.initialize()
    async def run():
        lab, _ = await setup()
        payload = build_snapshot(lab.source, lab.run_id, 0)
        assert inbox.save(bucket(payload, 2))
        assert not inbox.save(bucket(payload, 1))
        assert not inbox.save(bucket(payload, 2))
        assert NarrativeInbox(store).read(payload.snapshot.id)['audience_revision'] == 2
        assert inbox.latest_cursor(payload.snapshot.run_id, 5) == 0
        assert inbox.latest_cursor('another-run', 5) is None
    asyncio.run(run())


def test_inactive_run_narratives_never_enter_current_inbox():
    async def run():
        lab, _ = await setup()
        inbox = SimpleNamespace(save=lambda _: pytest.fail('Old run saved'))
        runtime = BrokerRuntime(lab, None, inbox)
        delivery = bucket(build_snapshot(lab.source, 'old-run', 0))
        await runtime.accept_narrative(delivery)
    asyncio.run(run())


def test_broker_question_capture_only_reads_graphql():
    import httpx
    requests = []
    async def run():
        lab, _ = await setup()
        payload = build_snapshot(lab.source, lab.run_id, 0)
        def respond(request):
            requests.append(request.url.path)
            assert request.url.path == '/graphql'
            return httpx.Response(200, json={'data': {'questionData': {
                'snapshot_id': payload.snapshot.id, 'match_id': payload.snapshot.match_id,
                'complete': True, 'stats': []}}})
        client = BrokerQuestionData('http://etl/graphql', operation='stats', transport=httpx.MockTransport(respond))
        await client.capture(payload)
    asyncio.run(run())
    assert requests == ['/graphql']


def test_expired_narrative_lock_reconnects_instead_of_retrying_dead_delivery():
    from datetime import datetime, timezone, timedelta
    async def run():
        lab, _ = await setup()
        body = bucket(build_snapshot(lab.source, lab.run_id, 0)).model_dump_json()
        class Message:
            locked_until_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
            def __str__(self):
                return body
        receiver, accept = AsyncMock(), AsyncMock(side_effect=OSError())
        with pytest.raises(RuntimeError, match='lock expired'):
            await settle_bucket_message(receiver, Message(), accept)
        receiver.complete_message.assert_not_awaited()
        receiver.abandon_message.assert_not_awaited()
    asyncio.run(run())
