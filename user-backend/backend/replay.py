"""Replay hand-authored synthetic events through the two fake services."""
import argparse
import json
import os
import time
from pathlib import Path

import httpx


def entries():
    path = Path(__file__).parent.parent / "fixtures/opta-style.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def replay(etl_url, narrative_url, interval=0.5):
    with httpx.Client(timeout=30) as client:
        for item in entries():
            url = etl_url + "/events" if item["kind"] == "event" else narrative_url + "/narratives"
            response = client.post(url, json=item["payload"])
            response.raise_for_status()
            payload = item["payload"]
            print(f"SYNTHETIC {item['kind']}: {payload.get('eventId', payload.get('id'))}", flush=True)
            if interval:
                time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds between messages; not match-clock speed")
    args = parser.parse_args()
    if args.interval < 0:
        parser.error("interval must be nonnegative")
    replay(os.getenv("FAKE_ETL_URL", "http://fake-etl:8000"),
           os.getenv("FAKE_NARRATIVE_URL", "http://fake-narrative:8000"), args.interval)


if __name__ == "__main__":
    main()
