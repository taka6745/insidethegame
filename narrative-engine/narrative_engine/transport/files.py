"""Local transport: replay ETL notifications from JSONL and write narratives to JSONL."""
import asyncio
import json
from dataclasses import asdict

from narrative_engine.core.models import MatchClock, Narrative, Trigger, parse_notification, parse_time


def narrative_doc(narrative):
    doc = asdict(narrative)
    doc["matchTime"]["label"] = narrative.matchTime.label
    doc["trigger"]["eventIds"] = list(narrative.trigger.eventIds)
    return doc


def narrative_from_doc(doc):
    trigger = {**doc["trigger"], "eventIds": tuple(doc["trigger"].get("eventIds") or ())}
    clock = doc["matchTime"]
    return Narrative(**{**doc, "trigger": Trigger(**trigger), "matchTime": MatchClock(clock["periodId"], clock["timeMin"])})


def read_narratives(path):
    with open(path, encoding="utf-8") as f:
        return [narrative_from_doc(json.loads(line)) for line in f if line.strip()]


class MemorySink:
    def __init__(self, store=None):
        self.published, self.store = [], store

    async def publish(self, narrative):
        if self.store is not None:  # tests: narratives must be persisted before they are published
            assert await self.store.narrative_for_step(narrative.matchId, narrative.userType, narrative.stepId)
        self.published.append(narrative)


class JsonlSink:
    def __init__(self, path):
        self.path = path

    async def publish(self, narrative):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(narrative_doc(narrative)) + "\n")


def read_notifications(path, match_id=None):
    """Parsed messages from an ETL notifications file, optionally re-addressed to `match_id`."""
    with open(path) as f:
        bodies = [json.loads(line) for line in f if line.strip()]
    if match_id:
        bodies = [{**b, "matchId": match_id} for b in bodies]
    return [(b, parse_notification(b)) for b in bodies]


def _sent_at(body):
    return parse_time(body.get("windowEnd") or body.get("eventTime") or body["sentAt"])


async def replay(path, handle, pace=0.0, match_id=None):
    """Feed notifications to `handle`.

    pace 0 handles each message in turn, as fast as possible. pace > 0 sleeps for the
    recorded gaps divided by `pace` and handles messages concurrently, as a Service Bus
    listener would.
    """
    messages = [(b, m) for b, m in read_notifications(path, match_id) if m is not None]
    if pace <= 0:
        for _, message in messages:
            await handle(message)
        return
    start, tasks = _sent_at(messages[0][0]), []
    loop_start = asyncio.get_running_loop().time()
    for body, message in messages:
        due = loop_start + (_sent_at(body) - start).total_seconds() / pace
        await asyncio.sleep(max(0.0, due - asyncio.get_running_loop().time()))
        tasks.append(asyncio.create_task(handle(message)))
    await asyncio.gather(*tasks)
