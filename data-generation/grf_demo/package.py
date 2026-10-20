"""Package a real-time capture: broadcast score strip, faststart MP4 and playback metadata."""

import argparse
import gzip
import json
from pathlib import Path
import subprocess

from .opta import export


def broadcast_clock(video_seconds, period_starts, half_seconds=2700):
    """Match clock as broadcast: runs through dead play; the second half starts at 45:00."""
    period = 2 if len(period_starts) > 1 and video_seconds >= period_starts[1] else 1
    elapsed = max(0, video_seconds - period_starts[period - 1])
    return int(elapsed + (half_seconds if period == 2 else 0))


def period_starts(source):
    starts, last = [], None
    with gzip.open(source / "frames.jsonl.gz", "rt") as frames:
        for line in frames:
            state = json.loads(line)
            if state["phase"] in (1, 2) and state["phase"] != last:
                starts.append(state["video_seconds"])
                last = state["phase"]
    return starts


def package(source, output, render=True):
    recording = json.loads((source / "recording.native.json").read_text())
    provenance = recording["provenance"]
    half = provenance["active_play_seconds"] // 2
    duration = provenance["native_video_seconds"]
    recording["playback"] = {
        "duration_seconds": duration,
        "football_duration_seconds": 2 * half,
        "halftime_seconds": provenance["native_halftime_video_seconds"],
    }
    recording["duration_seconds"] = duration
    recording["halftime_seconds"] = provenance["native_halftime_video_seconds"]
    provenance["presentation"] = (
        "Real time: video seconds equal capture seconds. The broadcast clock runs through "
        "dead play, so each half ends in stoppage time."
    )
    if render:
        render_strip(source, period_starts(source), half)
        segment(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(recording, separators=(",", ":")))
    output.with_name(output.stem + ".opta-f24.json").write_text(json.dumps(export(recording), separators=(",", ":")))
    return recording


def segment(source):
    """Two-second HLS segments (keyframe every 50 frames) for live and replay playlists."""
    target = source / "hls"
    target.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(source / "match.mp4"), "-c", "copy", "-f", "hls",
         "-hls_time", "2", "-hls_playlist_type", "vod", "-hls_segment_filename", str(target / "%05d.ts"),
         "-y", str(target / "match.m3u8")],
        check=True,
    )


def render_strip(source, starts, half):
    import cv2
    import numpy as np

    # A crisp PL-inspired score strip over the simulator's original HUD.
    # The rest of each frame is untouched; native score changes drive the score.
    raw = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(source / "native.mp4"),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        stdout=subprocess.PIPE,
    )
    scored = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720",
         "-r", "25", "-i", "pipe:0", "-an", "-c:v", "h264_videotoolbox", "-b:v", "5M",
         "-g", "50", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(source / "match.mp4")],
        stdin=subprocess.PIPE,
    )
    font = cv2.FONT_HERSHEY_DUPLEX
    try:
        with gzip.open(source / "frames.jsonl.gz", "rt") as frames:
            for line in frames:
                state = json.loads(line)
                pixels = raw.stdout.read(1280 * 720 * 3)
                if len(pixels) != 1280 * 720 * 3:
                    raise ValueError("Native video/frame telemetry mismatch")
                image = np.frombuffer(pixels, dtype=np.uint8).reshape(720, 1280, 3).copy()
                # Original scorebug occupies x210..605 at720p.
                cv2.rectangle(image, (205, 13), (610, 49), (35, 0, 46), -1)
                cv2.rectangle(image, (304, 13), (421, 49), (0, 255, 135), -1)
                cv2.rectangle(image, (205, 13), (211, 49), (15, 80, 235), -1)
                cv2.rectangle(image, (604, 13), (610, 49), (220, 20, 45), -1)
                score = f"{state['score'][0]}  -  {state['score'][1]}"
                clock = broadcast_clock(state["video_seconds"], starts, half)
                cv2.putText(image, "CHE", (226, 38), font, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(image, score, (322, 38), font, 0.65, (35, 0, 46), 1, cv2.LINE_AA)
                cv2.putText(image, "MUN", (438, 38), font, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(image, f"{clock // 60:02}:{clock % 60:02}", (523, 38), font, 0.53,
                            (255, 255, 255), 1, cv2.LINE_AA)
                scored.stdin.write(image.tobytes())
    finally:
        raw.stdout.close()
        scored.stdin.close()
        if raw.wait(timeout=60) or scored.wait(timeout=60):
            raise RuntimeError("Scoreboard encoding failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()
    package(args.source, args.output, not args.no_video)
