"""Publish the three synthetic development events, not a full match replay."""

import json
from pathlib import Path

from azure.eventhub import EventData, EventHubProducerClient
from settings import EVENTHUB, EVENTHUB_CONNECTION


def main():
    events = [json.loads(line) for line in
              (Path(__file__).parent / "fixtures/match-events.jsonl").read_text().splitlines()]
    with EventHubProducerClient.from_connection_string(EVENTHUB_CONNECTION, eventhub_name=EVENTHUB) as producer:
        batch = producer.create_batch(partition_key="synthetic-demo")
        for event in events:
            batch.add(EventData(json.dumps(event)))
        producer.send_batch(batch)
    print("Sent 3 synthetic fixture events. Original IDs/timestamps retained; no clock rebasing or ETL performed.")


if __name__ == "__main__":
    main()
