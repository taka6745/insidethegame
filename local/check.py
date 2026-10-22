"""Dependency integration checks. Does not pretend to run application services."""

import argparse
import asyncio
import json
import time
import urllib.request
import uuid

import psycopg
from azure.cosmos import CosmosClient, PartitionKey
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubConsumerClient, EventHubProducerClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from settings import (
    COSMOS_ENDPOINT, COSMOS_KEY, ETL_GRAPHQL, EVENTHUB, EVENTHUB_CONNECTION,
    POSTGRES_DSN, SERVICEBUS_CONNECTION,
)

def wait_for(label, operation, timeout=180):
    print(f"Checking {label} (startup allowance: {timeout}s)", flush=True)
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = operation()
            print(f"PASS {label}", flush=True)
            return value
        except Exception as exc:
            last_error = exc
            time.sleep(3)
    raise RuntimeError(f"{label} did not become ready: {last_error}") from last_error


def postgres_check():
    # Both backend databases; their schemas belong to user-backend/migrations. Temp tables only.
    for database in ("accounts", "matchapp"):
        with psycopg.connect(POSTGRES_DSN + f" dbname={database}", connect_timeout=5) as conn:
            conn.execute("CREATE TEMP TABLE integration_probe (value text)")
            conn.execute("INSERT INTO integration_probe VALUES (%s)", ("round-trip",))
            assert conn.execute("SELECT value FROM integration_probe").fetchone()[0] == "round-trip"


def cosmos_check():
    with CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY, enable_endpoint_discovery=False,
                      connection_timeout=5, request_timeout=10) as client:
        db = client.create_database_if_not_exists("narrative")
        for name in ("contextBlocks", "narratives", "checkpoints"):
            db.create_container_if_not_exists(name, partition_key=PartitionKey(path="/matchId"))
        container = db.get_container_client("narratives")
        item = {"id": str(uuid.uuid4()), "matchId": "integration-only", "text": "Synthetic probe"}
        container.upsert_item(item)
        assert container.read_item(item["id"], partition_key=item["matchId"])["text"] == item["text"]
        container.delete_item(item["id"], partition_key=item["matchId"])


def etl_graphql_check():
    # Read-only: the ETL's own DAB (etl/dab) over its migrated `insidethegame` schema. Writes nothing.
    query = "{ statDefinitions(first: 1) { items { statId } } matches(first: 1) { items { matchId } } }"
    request = urllib.request.Request(ETL_GRAPHQL, data=json.dumps({"query": query}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.load(response)
    assert not body.get("errors"), body
    assert body["data"]["statDefinitions"]["items"], "ETL stat catalogue is empty"


async def eventhubs_check():
    probe = str(uuid.uuid4())
    seen = asyncio.Event()
    consumer = EventHubConsumerClient.from_connection_string(
        EVENTHUB_CONNECTION, consumer_group="integration", eventhub_name=EVENTHUB)

    async def on_event(context, event):
        if event and json.loads(event.body_as_str()).get("testRunId") == probe:
            seen.set()

    async with consumer:
        receive_task = asyncio.create_task(consumer.receive(on_event, starting_position="-1"))
        try:
            async with EventHubProducerClient.from_connection_string(
                EVENTHUB_CONNECTION, eventhub_name=EVENTHUB
            ) as producer:
                batch = await producer.create_batch(partition_key="integration-only")
                batch.add(EventData(json.dumps({"type": "IntegrationProbe", "testRunId": probe, "synthetic": True})))
                await producer.send_batch(batch)
            await asyncio.wait_for(seen.wait(), timeout=45)
        finally:
            receive_task.cancel()
            await asyncio.gather(receive_task, return_exceptions=True)


def servicebus_check(topic):
    probe = str(uuid.uuid4())
    with ServiceBusClient.from_connection_string(SERVICEBUS_CONNECTION, retry_total=2) as client:
        with client.get_topic_sender(topic_name=topic) as sender:
            sender.send_messages(ServiceBusMessage(json.dumps({"type": "IntegrationProbe", "testRunId": probe}),
                                                   message_id=probe, content_type="application/json"))
        with client.get_subscription_receiver(topic_name=topic, subscription_name="integration",
                                              max_wait_time=5) as receiver:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                for message in receiver.receive_messages(max_message_count=20, max_wait_time=5):
                    matched = message.message_id == probe
                    receiver.complete_message(message)
                    if matched:
                        return
    raise RuntimeError(f"No matching message delivered through {topic}")


def health(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.status == 200


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["base", "azure"], default="base", nargs="?")
    mode = parser.parse_args().mode
    wait_for("Postgres: accounts + match database read/write", postgres_check)
    wait_for("Cosmos: containers + document round trip", cosmos_check)
    if mode == "azure":
        wait_for("ETL GraphQL: stat catalogue + matches through Data API builder", etl_graphql_check)
        wait_for("Event Hubs health", lambda: health("http://eventhubs:5300/health"))
        asyncio.run(asyncio.wait_for(eventhubs_check(), timeout=60))
        print("PASS Event Hubs: SDK publish/consume")
        wait_for("Service Bus health", lambda: health("http://servicebus:5300/health"))
        for topic in ("match-notifications", "narratives"):
            servicebus_check(topic)
            print(f"PASS Service Bus: {topic} topic/subscription round trip")
    print("Dependency checks passed. Stream Analytics, agents and frontend are NOT exercised.")


if __name__ == "__main__":
    main()
