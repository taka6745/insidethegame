"""Event Hubs consumer and Service Bus outbox sender (Azure SDKs)."""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

# Imported before the sender and consumer threads start: concurrent first imports of azure.core
# fail with a circular ImportError.
from azure.eventhub import EventHubConsumerClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage

log = logging.getLogger(__name__)
STARTUP_WINDOW = timedelta(minutes=2)


def consume(worker, connection_string, hub, consumer_group):
    """Resume each partition after its committed checkpoint; without one, start shortly before now
    (old runs in retention are not replayed). Any failure reloads state and reconnects."""
    while True:
        try:
            consume_once(worker, EventHubConsumerClient.from_connection_string(
                connection_string, consumer_group=consumer_group, eventhub_name=hub))
        except Exception as exc:
            log.warning("Event Hubs consumer will reconnect (%s)", type(exc).__name__)
        time.sleep(2)


def past_end(client, positions):
    """{partition: (position, last)} for sequence positions past the partition's last enqueued
    sequence number: the hub was recreated (the emulator restarts at 0)."""
    stale = {}
    for p, position in list(positions.items()):
        if isinstance(position, int):
            last = client.get_partition_properties(p)["last_enqueued_sequence_number"]
            if position > last:
                stale[p] = (position, last)
    return stale


def consume_once(worker, client, check_seconds=5.0):
    """One connection until a batch fails to commit or a partition is found reset; the caller
    reconnects. A reset partition restarts from the startup window ("latest")."""
    failed = threading.Event()
    positions = {}

    def on_batch(context, events):
        if failed.is_set():
            return  # Uncommitted: redelivered after the reconnect.
        try:
            worker.handle(context.partition_id, [(e.sequence_number, e.body_as_str()) for e in events])
            if events:
                positions[context.partition_id] = events[-1].sequence_number
        except Exception as exc:
            log.warning("Batch not committed; reconnecting from checkpoints (%s)", type(exc).__name__)
            failed.set()

    try:
        checkpoints = worker.load()
        start = datetime.now(timezone.utc) - STARTUP_WINDOW
        positions.update({p: checkpoints.get(p, start) for p in client.get_partition_ids()})
        for p, (position, last) in past_end(client, positions).items():
            log.warning("Event Hubs partition %s ends at %s, before checkpoint %s: the hub was reset; "
                        "starting from latest", p, last, position)
            worker.reset_checkpoint(p)
            positions[p] = start
        receiver = threading.Thread(target=client.receive_batch, daemon=True, kwargs=dict(
            on_event_batch=on_batch, max_batch_size=200, max_wait_time=5,
            starting_position=dict(positions), starting_position_inclusive=False))
        receiver.start()
        checked = time.monotonic()
        while receiver.is_alive() and not failed.wait(1):
            # A reset while connected (emulator restart): the SDK would wait on old offsets silently.
            if time.monotonic() - checked >= check_seconds:
                checked = time.monotonic()
                if stale := past_end(client, positions):
                    for p, (position, last) in stale.items():
                        log.warning("Event Hubs partition %s ends at %s, before position %s: the hub was "
                                    "reset; reconnecting from latest", p, last, position)
                    failed.set()  # A batch from the old hub must not commit after the reset.
                    for p in stale:
                        worker.reset_checkpoint(p)
                    return
    finally:
        client.close()


def send_outbox(repository, connection_string, topic, poll_seconds=0.5):
    """Send unsent outbox rows in order; MessageId lets Service Bus drop resends."""
    while True:
        try:
            with ServiceBusClient.from_connection_string(connection_string) as client, \
                    client.get_topic_sender(topic_name=topic) as sender:
                while True:
                    rows = repository.pending_notifications()
                    if not rows:
                        time.sleep(poll_seconds)
                        continue
                    for seq, message_id, kind, body in rows:
                        sender.send_messages(ServiceBusMessage(
                            body, message_id=message_id, content_type="application/json",
                            application_properties={"notificationType": kind}))
                        repository.mark_sent([seq])
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log.warning("Service Bus sender will reconnect (%s)", type(exc).__name__)
            repository.rollback()
            time.sleep(2)
