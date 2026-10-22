"""Rebuild the delivery recording from preserved raw capture after adapter changes."""

import argparse
import gzip
import json
from pathlib import Path
from .roster import FIXTURE, FIXTURE_NAME, fixture_for
from .telemetry import TelemetryAdapter


def translate(source):
    path = source / "recording.native.json"
    recording = json.loads(path.read_text())
    if fixture_for(recording) is not FIXTURE:
        raise ValueError(f"Recording is not GRF_FIXTURE={FIXTURE_NAME}; set GRF_FIXTURE to its fixture")
    adapter = TelemetryAdapter(recording["provenance"].get("active_play_seconds", 5400) // 2)
    frames = 0
    last = None
    live_since, nudges = 0.0, []
    with gzip.open(source / "raw.jsonl.gz", "rt") as raw:
        for line in raw:
            row = json.loads(line)
            # Older local capture emitted exactly four100Hz frame records per25Hz video frame.
            # New captures preserve explicit batchtime on every row.
            video = row.get("capture_video_seconds", (frames // 4) / 25)
            adapter.consume(row, video)
            # Replays capture.py's stall rule, so nudges are traceable even for older captures.
            if row["kind"] == "touch" or (row["kind"] == "frame" and not row["in_play"]):
                live_since = video
            elif (row["kind"] == "frame" and row["owner"][0] in (0, 1) and video - live_since > 8
                  and (not nudges or video - nudges[-1] > 4)):
                nudges.append(round(video, 2))
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
    # Older captures only counted nudges; replay capture.py's rule for them, keep recorded times otherwise.
    if "stall_nudge_seconds" not in recording["provenance"]:
        recording["provenance"].pop("stall_nudges", None)
        recording["provenance"]["stall_nudge_seconds"] = nudges
    recording["provenance"]["contact_coalescing"] = (
        "Continuous same-player/function/type callbacks with gaps<=300ms form one action."
    )
    recording["provenance"]["scoring_attempts"] = (
        "A linked scored shot is represented once as goal; raw native shot remains in capture."
    )
    # The adapter attributes own goals since 22 Oct; older captures' limitation text says it does not.
    recording["provenance"]["limitations"] = [
        "No xG, substitutions, injuries or VAR." if line == "No xG, substitutions, injuries, VAR or own-goal attribution."
        else line for line in recording["provenance"].get("limitations", [])]
    path.write_text(json.dumps(recording, separators=(",", ":")))
    return recording


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    translate(parser.parse_args().source)
