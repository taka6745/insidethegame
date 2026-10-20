"""Replay a match file onto Event Hubs, or into a timestamped file for local loads.

Each period starts just after a window boundary, so one Stream Analytics
tumbling window holds exactly one match minute. The window length is
60 / speed seconds; the Stream Analytics job must use the same value.

    python -m seeder.replay seeder/matches/itg-syn-0001.jsonl --speed 10 --target file
    python -m seeder.replay seeder/matches/itg-syn-0001.jsonl --speed 10 --target eventhub

Event Hubs: set ETL_EVENTHUB_CONNECTION_STRING (send-only key; `terraform output -raw
eventhub_send_connection_string`), or ETL_EVENTHUB_NAMESPACE to use your Azure login.
"""
import argparse
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reference import opta


def window_seconds(speed):
    window = 60 / speed
    if window != int(window):
        raise SystemExit(f"--speed must divide 60 so windows are whole seconds (got {speed})")
    return int(window)


def next_boundary(t, window):
    return datetime.fromtimestamp(math.ceil(t.timestamp() / window) * window, timezone.utc)


def schedule(messages, match_id, speed, half_time_seconds, start=None):
    """Return messages with matchId and wall-clock timeStamp rewritten for this replay."""
    window = window_seconds(speed)
    # Half a match second after the boundary: second 59 still lands inside the minute's window.
    nudge = timedelta(seconds=0.5 / speed)
    now = start or datetime.now(timezone.utc)
    period_start, last = {}, now
    out = []
    for message in messages:
        message = {**message, "matchId": match_id}
        if message["feed"] == "MA3":
            period = message["periodId"]
            if period not in period_start:
                gap = timedelta(seconds=half_time_seconds if period_start else 5)
                period_start[period] = next_boundary(last + gap, window) + nudge
            clock = message["timeMin"] * 60 + message["timeSec"] - opta.PERIOD_START_MIN[period] * 60
            last = period_start[period] + timedelta(seconds=clock / speed)
        else:
            last = now
        message["timeStamp"] = last.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        out.append(message)
    return out


def send_to_eventhub(messages, namespace, hub):
    from azure.eventhub import EventData, EventHubProducerClient

    def due(message):
        return datetime.fromisoformat(message["timeStamp"].replace("Z", "+00:00"))

    connection_string = os.environ.get("ETL_EVENTHUB_CONNECTION_STRING")
    if connection_string:  # LATER: drop once Entra roles can be assigned
        producer = EventHubProducerClient.from_connection_string(connection_string, eventhub_name=hub)
    else:
        from azure.identity import DefaultAzureCredential
        producer = EventHubProducerClient(namespace, hub, DefaultAzureCredential())
    with producer:
        i = 0
        while i < len(messages):
            group = [messages[i]]
            while i + len(group) < len(messages) and due(messages[i + len(group)]) == due(group[0]):
                group.append(messages[i + len(group)])
            wait = (due(group[0]) - datetime.now(timezone.utc)).total_seconds()
            if wait > 0:
                time.sleep(wait)
            batch = producer.create_batch(partition_key=group[0]["matchId"])
            for message in group:
                batch.add(EventData(json.dumps(message, separators=(",", ":"))))
            producer.send_batch(batch)
            i += len(group)
            last = group[-1]
            if last["feed"] == "MA3" and last["timeSec"] == 0:
                print(f"sent seq {last['seq']} ({opta.minute_label(last['periodId'], last['timeMin'])})", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("--speed", type=float, default=1.0, help="match seconds per wall second; must divide 60")
    parser.add_argument("--match-id", help="default: source matchId plus a UTC run suffix, so reruns are new matches")
    parser.add_argument("--half-time-seconds", type=float, default=30, help="wall-clock gap between periods")
    parser.add_argument("--target", choices=["eventhub", "file"], default="file")
    parser.add_argument("--out", type=Path, help="file target path (default .local/replays/<matchId>.jsonl)")
    parser.add_argument("--namespace", default=os.environ.get("ETL_EVENTHUB_NAMESPACE"))
    parser.add_argument("--hub", default=os.environ.get("ETL_EVENTHUB_NAME", "match-events"))
    args = parser.parse_args()

    messages = [json.loads(line) for line in args.source.read_text(encoding="utf-8").splitlines() if line]
    match_id = args.match_id or f"{messages[0]['matchId']}-{datetime.now(timezone.utc):%Y%m%dT%H%M}"
    replay = schedule(messages, match_id, args.speed, args.half_time_seconds)
    print(f"match {match_id}: {len(replay)} messages, window {window_seconds(args.speed)}s, "
          f"kickoff {next(m['timeStamp'] for m in replay if m['feed'] == 'MA3')}")

    # Always keep the timestamped copy: `devtools verify` needs exactly what was sent.
    out = args.out or Path(__file__).resolve().parents[1] / ".local" / "replays" / f"{match_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(m, separators=(",", ":")) + "\n" for m in replay), encoding="utf-8")
    print(f"wrote {out}")
    if args.target == "eventhub":
        if not (args.namespace or os.environ.get("ETL_EVENTHUB_CONNECTION_STRING")):
            raise SystemExit("set ETL_EVENTHUB_CONNECTION_STRING, --namespace or ETL_EVENTHUB_NAMESPACE")
        send_to_eventhub(replay, args.namespace, args.hub)


if __name__ == "__main__":
    main()
