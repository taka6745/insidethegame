"""Make two six-minute video halves and apply the same clock to telemetry."""

import argparse
import json
from pathlib import Path
import subprocess


def presentation_time(seconds, halftime, duration):
    if not 0 < halftime < duration:
        raise ValueError("A complete two-half capture is required")
    if seconds <= halftime:
        return seconds * 360 / halftime
    return 360 + (seconds - halftime) * 360 / (duration - halftime)


def package(source, output, render=True):
    recording = json.loads((source / "recording.native.json").read_text())
    provenance = recording["provenance"]
    half = provenance["native_halftime_video_seconds"]
    duration = provenance["native_video_seconds"]
    for event in recording["events"]:
        event["videoSeconds"] = round(
            presentation_time(event["videoSeconds"], half, duration), 3
        )
    for sample in recording["possession_samples"]:
        sample["video_seconds"] = round(
            presentation_time(sample["video_seconds"], half, duration), 3
        )
    recording["playback"] = {
        "duration_seconds": 720,
        "football_duration_seconds": 5400,
        "halftime_seconds": 360,
    }
    recording["duration_seconds"] = 720
    recording["halftime_seconds"] = 360
    provenance["presentation"] = (
        "Each native half scaled independently to360 video seconds, including stoppages. Matchclock90 minutes; activephysics12 minutes."
    )
    if render:
        import cv2
        import numpy as np

        # Render a crisp PL-inspired score strip over the simulator's original HUD.
        # The rest of each frame is untouched; match events drive every score change.
        raw = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(source / "native.mp4"),
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
        )
        scored = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                "1280x720",
                "-r",
                "25",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "h264_videotoolbox",
                "-b:v",
                "5M",
                "-y",
                str(source / "styled.mp4"),
            ],
            stdin=subprocess.PIPE,
        )
        import gzip

        try:
            with gzip.open(source / "frames.jsonl.gz", "rt") as frames:
                for line in frames:
                    state = json.loads(line)
                    pixels = raw.stdout.read(1280 * 720 * 3)
                    if len(pixels) != 1280 * 720 * 3:
                        raise ValueError("Native video/frame telemetry mismatch")
                    image = (
                        np.frombuffer(pixels, dtype=np.uint8)
                        .reshape(720, 1280, 3)
                        .copy()
                    )
                    # Original scorebug occupies x210..605 at720p.
                    cv2.rectangle(image, (205, 13), (610, 49), (35, 0, 46), -1)
                    cv2.rectangle(image, (304, 13), (421, 49), (0, 255, 135), -1)
                    cv2.rectangle(image, (205, 13), (211, 49), (15, 80, 235), -1)
                    cv2.rectangle(image, (604, 13), (610, 49), (220, 20, 45), -1)
                    score = f"{state['score'][0]}  -  {state['score'][1]}"
                    clock = int(min(5400, state["match_ms"] * 7.5 / 1000))
                    cv2.putText(
                        image,
                        "CHE",
                        (226, 38),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.65,
                        (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )
                    cv2.putText(
                        image,
                        score,
                        (322, 38),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.65,
                        (35, 0, 46),
                        1,
                        cv2.LINE_AA,
                    )
                    cv2.putText(
                        image,
                        "MUN",
                        (438, 38),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.65,
                        (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )
                    cv2.putText(
                        image,
                        f"{clock // 60:02}:{clock % 60:02}",
                        (523, 38),
                        cv2.FONT_HERSHEY_DUPLEX,
                        0.53,
                        (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )
                    scored.stdin.write(image.tobytes())
        finally:
            raw.stdout.close()
            scored.stdin.close()
            if raw.wait(timeout=60) or scored.wait(timeout=60):
                raise RuntimeError("Scoreboard encoding failed")
        graph = (
            f"[0:v]split=2[a][b];[a]trim=end={half},setpts=(PTS-STARTPTS)*{360 / half}[h1];"
            f"[b]trim=start={half},setpts=(PTS-STARTPTS)*{360 / (duration - half)}[h2];"
            "[h1][h2]concat=n=2:v=1:a=0,fps=25[v]"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(source / "styled.mp4"),
                "-filter_complex",
                graph,
                "-map",
                "[v]",
                "-t",
                "720",
                "-c:v",
                "h264_videotoolbox",
                "-b:v",
                "5M",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-y",
                str(source / "match.mp4"),
            ],
            check=True,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(recording, separators=(",", ":")))
    return recording


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()
    package(args.source, args.output, not args.no_video)
