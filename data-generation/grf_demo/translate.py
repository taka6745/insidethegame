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
    adapter.finish(last, duration)
    recording["events"] = adapter.canonical_events()
    recording["possession_samples"] = adapter.possession_samples
    recording["capabilities"] = adapter.capabilities()
    recording["provenance"]["telemetry_version"] = adapter.version
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
