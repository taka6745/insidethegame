import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from narrative_demo.adapters.service_bus import handle_message
from narrative_demo.app import create_app
from narrative_demo.models.brokers import SnapshotReady
from narrative_demo.repositories.snapshots import SnapshotRepository
from narrative_demo.services.broker_delivery import NarrativeDelivery
from test_narrative_demo import payload, setup


def metadata(cursor=2, run='run', captured='2026-10-19T01:00:00+00:00'):
    value = payload().model_dump()
    value['snapshot'].update(cursor=cursor, run_id=run, captured_at=captured, id=f'{run}-{cursor}')
    value['events'] = []
    return SnapshotReady.model_validate({'type': 'MatchSnapshotReady', 'version': 1, 'snapshot': value}).snapshot


class Service:
    def __init__(self, repository):
        self.repository = repository
        self.capture = AsyncMock()
        self.document = {'items': [{'id': 'narrative', 'text': 'Chelsea keep possession.'}],
                         'events': [], 'audience_revision': 'one'}

    def read(self, snapshot_id, operation):
        assert operation == 'viewer'
        return self.document


def test_archive_then_send_then_settle_and_duplicate_recovers_lost_delivery():
    async def check():
        service = Service(SnapshotRepository(':memory:'))
        publisher = AsyncMock()
        delivery = NarrativeDelivery(service, publisher)
        receiver = AsyncMock()
        message = json.dumps({'type': 'MatchSnapshotReady', 'version': 1, 'snapshot': metadata().model_dump()})
        async def sent(body, signature):
            service.capture.assert_awaited_once()
            receiver.complete_message.assert_not_awaited()
            assert body['snapshot']['cursor'] == 2
            assert body['items'] == service.document['items']
        publisher.send.side_effect = sent
        await handle_message(receiver, message, delivery)
        receiver.complete_message.assert_awaited_once_with(message)
        publisher.send.side_effect = None
        # Simulate a lost emulator queue after the first successful send. A new
        # input notification must replenish delivery despite the saved signature.
        delivery = NarrativeDelivery(service, publisher)
        await handle_message(receiver, message, delivery)
        assert publisher.send.await_count == 2
        await delivery.refresh()
        assert publisher.send.await_count == 2
        assert service.repository.delivery_state()['metadata']['snapshot']['id'] == 'run-2'
    asyncio.run(check())


def test_long_publish_outage_retries_in_place_then_completes_once(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr('narrative_demo.adapters.service_bus.asyncio.sleep', sleep)
    async def check():
        service = Service(SnapshotRepository(':memory:'))
        publisher = AsyncMock()
        publisher.send.side_effect = [RuntimeError('unavailable')] * 12 + [None]
        delivery = NarrativeDelivery(service, publisher)
        receiver = AsyncMock()
        message = json.dumps({'type': 'MatchSnapshotReady', 'version': 1, 'snapshot': metadata().model_dump()})
        await handle_message(receiver, message, delivery)
        receiver.abandon_message.assert_not_awaited()
        receiver.dead_letter_message.assert_not_awaited()
        receiver.complete_message.assert_awaited_once_with(message)
        assert publisher.send.await_count == 13
        assert sleep.await_count == 12
        assert max(call.args[0] for call in sleep.await_args_list) == 15
        assert service.repository.delivery_state()['metadata']['snapshot']['id'] == 'run-2'
    asyncio.run(check())


def test_cancel_during_transient_retry_propagates_without_settlement(monkeypatch):
    monkeypatch.setattr('narrative_demo.adapters.service_bus.asyncio.sleep',
                        AsyncMock(side_effect=asyncio.CancelledError))
    async def check():
        receiver, delivery = AsyncMock(), AsyncMock()
        delivery.capture.side_effect = RuntimeError('upstream unavailable')
        message = json.dumps({'type': 'MatchSnapshotReady', 'version': 1, 'snapshot': metadata().model_dump()})
        with pytest.raises(asyncio.CancelledError):
            await handle_message(receiver, message, delivery)
        receiver.complete_message.assert_not_awaited()
        receiver.abandon_message.assert_not_awaited()
        receiver.dead_letter_message.assert_not_awaited()
    asyncio.run(check())


def test_expired_lock_escapes_for_broker_redelivery():
    class ExpiredMessage:
        auto_renew_error = RuntimeError('lock renewal expired')

        def __str__(self):
            return json.dumps({'type': 'MatchSnapshotReady', 'version': 1, 'snapshot': metadata().model_dump()})

    async def check():
        receiver, delivery = AsyncMock(), AsyncMock()
        delivery.capture.side_effect = RuntimeError('upstream unavailable')
        with pytest.raises(RuntimeError, match='lock expired'):
            await handle_message(receiver, ExpiredMessage(), delivery)
        receiver.complete_message.assert_not_awaited()
        receiver.abandon_message.assert_not_awaited()
    asyncio.run(check())


@pytest.mark.parametrize('body', ['not JSON', '{}', '[1]', json.dumps({'type': 'MatchSnapshotReady', 'version': 2})])
def test_invalid_notification_dead_letters(body):
    receiver, delivery = AsyncMock(), AsyncMock()
    asyncio.run(handle_message(receiver, body, delivery))
    receiver.dead_letter_message.assert_awaited_once()
    receiver.complete_message.assert_not_awaited()
    delivery.capture.assert_not_awaited()


def test_probe_is_settled_without_capture():
    receiver, delivery = AsyncMock(), AsyncMock()
    asyncio.run(handle_message(receiver, '{"type":"IntegrationProbe"}', delivery))
    receiver.complete_message.assert_awaited_once()
    delivery.capture.assert_not_awaited()


def test_restart_refreshes_audience_without_republishing_unchanged(tmp_path):
    async def check():
        path = str(tmp_path / 'archive.db')
        service = Service(SnapshotRepository(path))
        publisher = AsyncMock()
        delivery = NarrativeDelivery(service, publisher)
        await delivery.capture(metadata())
        service.repository.close()
        service = Service(SnapshotRepository(path))
        delivery = NarrativeDelivery(service, publisher)
        await delivery.refresh()
        assert publisher.send.await_count == 1
        service.document['items'] = []
        service.document['audience_revision'] = 'two'
        await delivery.refresh()
        assert publisher.send.await_count == 2
        assert publisher.send.call_args.args[0]['items'] == []
    asyncio.run(check())


def test_regressive_cursor_and_old_runs_do_not_replace_latest():
    async def check():
        service = Service(SnapshotRepository(':memory:'))
        publisher = AsyncMock()
        delivery = NarrativeDelivery(service, publisher)
        await delivery.capture(metadata(10))
        await delivery.capture(metadata(2))
        await delivery.capture(metadata(2, 'new', '2026-10-19T02:00:00+00:00'))
        await delivery.capture(metadata(20))
        assert publisher.send.await_count == 2
        assert delivery.latest.snapshot.run_id == 'new'
        await delivery.refresh()
        assert service.capture.call_args.args[0].snapshot.run_id == 'new'
    asyncio.run(check())


def test_broker_mode_disables_http_capture_but_keeps_graphql(tmp_path):
    service, source, meta, audience = setup(tmp_path)
    app = create_app(service, broker=AsyncMock())
    with TestClient(app) as client:
        for route in ('viewer', 'question'):
            response = client.post(f'/demo/{route}-snapshots', json=meta.model_dump())
            assert response.status_code == 409
        assert client.get('/health').json()['transport'] == 'service-bus'
        response = client.post('/graphql', json={'query': '{__typename}'})
        assert response.json()['data']['__typename'] == 'Query'
    assert audience.calls == 0


def test_out_of_order_snapshot_archives_neutral_context_without_live_publish():
    async def check():
        service = Service(SnapshotRepository(':memory:'))
        publisher = AsyncMock()
        delivery = NarrativeDelivery(service, publisher)
        await delivery.capture(metadata(10))
        older = metadata(2)
        await delivery.capture(older)
        service.capture.assert_awaited_with(older, viewer=False)
        assert publisher.send.await_count == 1
        assert delivery.latest.snapshot.cursor == 10
        assert service.repository.delivery_state()['metadata']['snapshot']['cursor'] == 10
    asyncio.run(check())


def test_final_cursor_cannot_roll_back_period_or_finished_clock():
    async def check():
        service = Service(SnapshotRepository(':memory:'))
        publisher = AsyncMock()
        delivery = NarrativeDelivery(service, publisher)
        final = metadata(10)
        final.snapshot.period = 2
        final.snapshot.clock_seconds = 5400
        final.snapshot.id = 'full-time'
        await delivery.capture(final)
        for period, clock in ((2, 5380), (1, 5400)):
            older = metadata(10)
            older.snapshot.period = period
            older.snapshot.clock_seconds = clock
            older.snapshot.id = f'earlier-{period}-{clock}'
            await delivery.capture(older)
            service.capture.assert_awaited_with(older, viewer=False)
        assert publisher.send.await_count == 1
        assert delivery.latest.snapshot.id == 'full-time'
        assert service.repository.delivery_state()['metadata']['snapshot']['clock_seconds'] == 5400
        await delivery.refresh()
        service.capture.assert_awaited_with(final, viewer=True)
        assert publisher.send.await_count == 1
    asyncio.run(check())
