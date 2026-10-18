"""Rebuild the delivery recording from preserved raw capture after adapter changes."""

import argparse
import gzip
import json
from pathlib import Path
from .telemetry import TelemetryAdapter


def translate(source):
    path = source / "recording.native.json"
    recording = json.loads(path.read_text())
    adapter = TelemetryAdapter()
    frames = 0
    last = None
    with gzip.open(source / "raw.jsonl.gz", "rt") as raw:
        for line in raw:
            row = json.loads(line)
            # Older local capture emitted exactly four100Hz frame records per25Hz video frame.
            # New captures preserve explicit batchtime on every row.
            video = row.get("capture_video_seconds", (frames // 4) / 25)
            adapter.consume(row, video)
            if row["kind"] == "frame":
                frames += 1
                last = row
    duration = recording["provenance"]["native_video_seconds"]
    if frames != round(duration * 25) * 4:
        raise ValueError(
            "Raw physics frames do not match fixed-rate capture; cannot infer alignment"
        )
    adapter.finish_pass(last, duration)
    adapter.flush(last, duration)
    recording["events"] = adapter.canonical_events()
    recording["possession_samples"] = adapter.possession_samples
    recording["capabilities"] = {
        "supported_event_types": ["touch", "pass", "shot", "goal"],
        "shot_outcomes": False,
        "distance_event_types": ["pass"],
        "body_parts": False,
        "shots_include_scoring_attempts": False,
        "possession_basis": "confirmed_native_ownership",
    }
    recording["provenance"]["contact_coalescing"] = (
        "Continuous same-player/function/type callbacks with gaps<=300ms form one action."
    )
    recording["provenance"]["scoring_attempts"] = (
        "A linked scoredshot is represented once as goal; raw native shot remains in capture."
    )
    path.write_text(json.dumps(recording, separators=(",", ":")))
    return recording


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    translate(parser.parse_args().source)
