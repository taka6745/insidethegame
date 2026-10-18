import asyncio
from unittest.mock import AsyncMock

from backend.adapters.narratives import settle_narrative
from backend.domain import Narrative, RuleError


def narrative():
    return Narrative(id='upstream-1', match_id='synthetic-demo', team='home', fan_style='simple',
                     minute=64, text='This exact wording was already framed upstream.')


def test_bucketed_text_is_delivered_unchanged_without_a_model(monkeypatch):
    from backend.adapters.llm import LocalJsonModel
    def forbidden(*args, **kwargs):
        raise AssertionError('Narrative routing must never call a framing model')
    monkeypatch.setattr(LocalJsonModel, 'complete', forbidden)
    receiver, deliver = AsyncMock(), AsyncMock()
    body = narrative()
    asyncio.run(settle_narrative(receiver, body.model_dump_json(), deliver))
    deliver.assert_awaited_once_with(body)
    receiver.complete_message.assert_awaited_once()
    receiver.dead_letter_message.assert_not_awaited()


def test_neutral_payload_is_rejected_before_routing():
    receiver, deliver = AsyncMock(), AsyncMock()
    asyncio.run(settle_narrative(receiver, '{"id":"neutral","match_id":"synthetic-demo",'
                                '"minute":64,"text":"Needs upstream framing"}', deliver))
    deliver.assert_not_awaited()
    receiver.dead_letter_message.assert_awaited_once()
    receiver.complete_message.assert_not_awaited()


def test_transient_delivery_failure_is_not_acknowledged(monkeypatch):
    receiver = AsyncMock()
    deliver = AsyncMock(side_effect=RuleError('upstream_unavailable', 'Retry', 503))
    monkeypatch.setattr('backend.adapters.narratives.asyncio.sleep', AsyncMock())
    asyncio.run(settle_narrative(receiver, narrative().model_dump_json(), deliver))
    receiver.abandon_message.assert_awaited_once()
    receiver.complete_message.assert_not_awaited()


def test_backend_has_no_neutral_framing_or_audience_authoring_routes(client):
    assert client.post('/dev/neutral-narratives', json={}).status_code == 404
    assert client.put('/dev/audiences', json={}).status_code == 404
    assert client.get('/audiences').status_code == 404


def test_product_rejects_legacy_service_bus_ingress_before_startup():
    import pytest
    from backend.app import create_app

    with pytest.raises(ValueError, match="legacy viewer harness"):
        create_app(enable_product=True, lab=object(), questions=object(),
                   narrative_connection="local-test-connection")
