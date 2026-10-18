"""Shared fanout, transport retries and socket lifecycle regression tests."""
import asyncio
from uuid import uuid4

import pytest

from backend.domain import MatchEvent, Narrative, RuleError
from backend.fixtures import FixtureFeed
from backend.routes.viewers import stream_viewer
from backend.services.live_viewers import ViewerPeer
from backend.services.viewers import ViewerService


def row(profile, team='home', style='analytical', pins=()):
    return {'profile_id': profile, 'state': {'team': team, 'fan_style': style, 'pins': list(pins)}}


def narrative():
    return Narrative(id='new', match_id='synthetic-demo', team='home', fan_style='analytical',
                     minute=30, text='A supplied narrative.')


class CountingFeed(FixtureFeed):
    def __init__(self):
        super().__init__('synthetic-demo', 3)
        self.calls = []
        self.unavailable = set()

    def view(self, bucket, team, calculation_ids=()):
        self.calls.append((bucket, tuple(calculation_ids)))
        if bucket in self.unavailable:
            raise RuleError('upstream_unavailable', 'Try again', 503)
        return super().view(bucket, team, calculation_ids)


def test_narrative_fetches_once_for_matching_bucket_and_preserves_personal_pins():
    async def run():
        feed = CountingFeed()
        service = ViewerService(None, feed, 'synthetic-demo', 3)
        first = service.live.attach(uuid4(), row('one', pins=['fixture-headers']))
        second = service.live.attach(uuid4(), row('two', pins=['fixture-saves']))
        unrelated = service.live.attach(uuid4(), row('three', 'away', 'casual'))
        feed.unavailable.add('away:casual')
        await service.deliver_narrative(narrative())
        assert feed.calls == [('home:analytical', ('fixture-headers', 'fixture-saves'))]
        assert unrelated.queue.empty()
        for peer, expected in [(first, 'fixture-headers'), (second, 'fixture-saves')]:
            assert peer.queue.get_nowait()['type'] == 'narrative'
            snapshot = peer.queue.get_nowait()['data']
            assert snapshot['cards'][-1]['id'] == expected
            assert snapshot['pins'] == [expected]
    asyncio.run(run())


def test_successful_redelivery_is_idempotent_and_changed_id_payload_is_rejected():
    async def run():
        feed = CountingFeed()
        service = ViewerService(None, feed, 'synthetic-demo', 3)
        peer = service.live.attach(uuid4(), row('one'))
        await service.deliver_narrative(narrative())
        response = await service.deliver_narrative(narrative())
        assert response['duplicate']
        assert peer.queue.qsize() == 2
        assert len(feed.calls) == 1
        assert sum(n.id == 'new' for n in feed.narratives) == 1
        with pytest.raises(RuleError, match='cannot change'):
            await service.deliver_narrative(narrative().model_copy(update={'text': 'Changed'}))
    asyncio.run(run())


def test_retry_after_upstream_failure_does_not_append_duplicate_history():
    async def run():
        feed = CountingFeed()
        service = ViewerService(None, feed, 'synthetic-demo', 3)
        peer = service.live.attach(uuid4(), row('one'))
        feed.unavailable.add('home:analytical')
        with pytest.raises(RuleError):
            await service.deliver_narrative(narrative())
        assert peer.queue.get_nowait()['type'] == 'error'
        assert peer.queue.empty()
        feed.unavailable.clear()
        await service.deliver_narrative(narrative())
        assert [peer.queue.get_nowait()['type'] for _ in range(2)] == ['narrative', 'snapshot']
        assert sum(n.id == 'new' for n in feed.narratives) == 1
    asyncio.run(run())


def test_slow_or_replaced_peer_stays_closed_and_does_not_receive_more_work():
    peer = ViewerPeer(uuid4(), row('one'))
    for _ in range(33):
        peer.offer({'type': 'update'})
    peer.offer({'type': 'late'})
    assert peer.closing
    assert peer.queue.get_nowait() == {'close': 1013}
    assert peer.queue.empty()


def test_socket_failure_before_initial_snapshot_cleans_up_peer():
    async def run():
        service = ViewerService(None, CountingFeed(), 'synthetic-demo', 3)
        token = uuid4()
        async def attach(token):
            return service.live.attach(token, row('one')), {}
        service.attach = attach
        class BrokenSocket:
            async def accept(self):
                raise RuntimeError('connection gone')
        with pytest.raises(RuntimeError, match='connection gone'):
            await stream_viewer(BrokenSocket(), service, token)
        assert service.live.peers == {}
    asyncio.run(run())


def test_pending_receipts_are_bounded_without_forgetting_unfinished_delivery():
    async def run():
        feed = CountingFeed()
        service = ViewerService(None, feed, 'synthetic-demo', 3, receipt_capacity=2)
        peer = service.live.attach(uuid4(), row('one'))
        feed.unavailable.add('home:analytical')
        for identifier in ('one', 'two'):
            with pytest.raises(RuleError, match='Try again'):
                await service.deliver_narrative(narrative().model_copy(update={'id': identifier}))
        with pytest.raises(RuleError) as exc:
            await service.deliver_narrative(narrative().model_copy(update={'id': 'three'}))
        assert exc.value.code == 'delivery_capacity'
        assert len(service._narrative_receipts) == 2
        assert not any(n.id == 'three' for n in feed.narratives)
        feed.unavailable.clear()
        await service.deliver_narrative(narrative().model_copy(update={'id': 'one'}))
        await service.deliver_narrative(narrative().model_copy(update={'id': 'three'}))
        assert len(service._narrative_receipts) == 2
        assert 'two' in service._narrative_receipts  # Unfinished delivery is retained.
        assert sum(n.id == 'one' for n in feed.narratives) == 1
    asyncio.run(run())


def test_duplicate_event_retries_failed_delivery_without_reapplying_event():
    async def run():
        feed = CountingFeed()
        service = ViewerService(None, feed, 'synthetic-demo', 3)
        peer = service.live.attach(uuid4(), row('one', pins=['fixture-headers']))
        event = MatchEvent(id='new-head', match_id='synthetic-demo', sequence=8,
                           minute=21, team='away', type='shot', body_part='head')
        feed.unavailable.add('home:analytical')
        with pytest.raises(RuleError):
            await service.accept_event(event)
        assert peer.queue.get_nowait()['type'] == 'error'
        feed.unavailable.clear()
        response = await service.accept_event(event)
        assert response['duplicate']
        assert peer.queue.get_nowait()['data']['cards'][-1]['value'] == 3
        calls = len(feed.calls)
        await service.accept_event(event)
        assert len(feed.calls) == calls  # Settled duplicates do not query upstream again.
        assert peer.queue.empty()
    asyncio.run(run())
