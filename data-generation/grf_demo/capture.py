"""Capture an installed, instrumented GRF runtime without importing archived scripts."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from .roster import TEAMS, players
from .scenario import REALISM
from .telemetry import TelemetryAdapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seconds", type=int, default=5400)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault("GRF_HIDDEN_WINDOW", "1")
    os.environ["GRF_HALF_SECONDS"] = str(args.seconds // 2)
    for name, value in REALISM.items():
        os.environ.setdefault(name, str(value))
    import gfootball.scenarios
    from gfootball.env import create_environment
    from gfootball.env.football_action_set import (action_builtin_ai, action_long_pass,
                                                    action_release_long_pass)

    gfootball.scenarios.__path__.append(str(Path(__file__).parent))
    env = create_environment(
        env_name="scenario",
        representation="raw",
        number_of_left_players_agent_controls=1,
        number_of_right_players_agent_controls=1,
        render=not args.no_video,
        write_video=False,
        other_config_options={
            "action_set": "v2",
            "game_engine_random_seed": args.seed,
            "real_time": False,
            "physics_steps_per_frame": 4,
            "render_resolution_x": 1280,
            "render_resolution_y": 720,
            "match_duration": 4.75,
        },
    )
    native = env.unwrapped._env._env
    native.drain_telemetry()
    native.telemetry_enabled = True
    for left in (True, False):
        native.perform_action(action_builtin_ai._backend_action, left, 0)
    adapter = TelemetryAdapter(args.seconds // 2)
    encoder = None
    if not args.no_video:
        encoder = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-f",
                "rawvideo",
                "-pixel_format",
                "rgb24",
                "-video_size",
                "1280x720",
                "-framerate",
                "25",
                "-i",
                "pipe:0",
                "-vf",
                "vflip",
                "-an",
                "-c:v",
                "h264_videotoolbox",
                "-b:v",
                "5M",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(args.output / "native.mp4"),
            ],
            stdin=subprocess.PIPE,
        )
    frames, halfway, last, started = 0, None, None, time.monotonic()
    live_since, nudged, nudges, pressed, nudge = 0.0, 0.0, [], None, []
    completed = False
    try:
        with (
            gzip.open(args.output / "raw.jsonl.gz", "wt", compresslevel=1) as raw_file,
            gzip.open(
                args.output / "frames.jsonl.gz", "wt", compresslevel=1
            ) as frame_file,
        ):
            while True:
                # Native AIs occasionally freeze around a stationary owner. The owner's team
                # presses and releases long pass (the native controller passes on release), then
                # control returns to the built-in AI. Each stall costs one counted nudge.
                if nudge:
                    native.perform_action(nudge.pop(0)._backend_action, pressed, 0)
                elif (last and last["in_play"] and last["owner"][0] in (0, 1)
                        and video - live_since > 8 and video - nudged > 4):
                    pressed = last["owner"][0] == 0
                    native.perform_action(action_long_pass._backend_action, pressed, 0)
                    nudge = [action_release_long_pass, action_builtin_ai]
                    nudged, nudges = video, nudges + [round(video, 2)]
                native.step()
                video = frames / 25
                for raw in native.drain_telemetry():
                    row = json.loads(raw)
                    raw_file.write(
                        json.dumps(
                            {**row, "capture_video_seconds": video},
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    adapter.consume(row, video)
                    if row["kind"] == "touch" or (row["kind"] == "frame" and not row["in_play"]):
                        live_since = video
                    if row["kind"] == "frame":
                        last = row
                        if row["phase"] >= 2 and halfway is None:
                            halfway = video
                if encoder:
                    encoder.stdin.write(native.get_frame())
                frame_file.write(
                    json.dumps(
                        {
                            "video_seconds": video,
                            "match_ms": last["match_ms"],
                            "phase": last["phase"],
                            "score": last["score"],
                        }
                    )
                    + "\n"
                )
                frames += 1
                if frames % 250 == 0:
                    progress = {
                        "video_seconds": frames / 25,
                        "match_seconds": last["match_ms"] / 1000,
                        "score": last["score"],
                        "render_fps": round(frames / (time.monotonic() - started), 1),
                    }
                    (args.output / "progress.json").write_text(json.dumps(progress))
                    print(json.dumps(progress), flush=True)
                if video - live_since > 60:
                    # Native AIs occasionally freeze around a stationary owner; never ship that.
                    raise RuntimeError(f"Simulation stalled at {video:.0f}s: no contact for 60 s of live play")
                if last["match_ms"] >= args.seconds * 1000:
                    completed = True
                    break
                if time.monotonic() - started > args.seconds * 10 / 3:
                    raise TimeoutError(
                        "Capture exceeded its time limit; partial outputs retained"
                    )
        adapter.finish(last, frames / 25)
    finally:
        if encoder:
            encoder.stdin.close()
            if encoder.wait(timeout=60):
                completed = False
        env.close()
    if not completed:
        raise RuntimeError("Incomplete recording")
    recording = {
        "schema_version": 1,
        "synthetic": True,
        "match_id": "product-demo-match",
        "description": "GRF simulated Chelsea–Manchester United. Illustrative real-name lineups; not an actual match.",
        "teams": TEAMS,
        "players": players(),
        "events": adapter.canonical_events(),
        "presets": [],
        "possession_samples": adapter.possession_samples,
        "capabilities": adapter.capabilities(),
        "provenance": {
            "telemetry_version": adapter.version,
            "generator": "data-generation/grf_demo/capture.py",
            "seed": args.seed,
            "source": "Google Research Football instrumented native runtime",
            "source_license": "Apache-2.0 / Gameplay Football Unlicense",
            "native_video_seconds": frames / 25,
            "native_halftime_video_seconds": halfway,
            "active_play_seconds": args.seconds,
            "realism": {name: float(os.environ[name]) for name in REALISM},
            # Scripted presses that un-freeze native AIs: traceable, never silent.
            "stall_nudge_seconds": nudges,
            "score": last["score"],
            "raw_sha256": hashlib.sha256(
                (args.output / "raw.jsonl.gz").read_bytes()
            ).hexdigest(),
            "limitations": [
                "Synthetic simulation, not official Opta data or an actual fixture.",
                "Names map simulator slots; player abilities are generic.",
                "Headed pass/shot classification requires an executed header with explicit native action intent.",
                "Pass completion means first subsequent intentional teammate touch; event time is resolution.",
                "Possession measures confirmed native ownership ticks; loose-ball and stoppage time excluded.",
                "Referee decisions and taken restarts are native observations; tackles, interceptions, saves, shot outcomes, aerials, take-ons and recoveries are rule-derived from native tracking (docs/opta-events.md).",
                "No xG, substitutions, injuries, VAR or own-goal attribution.",
                "Engine patched for realism (prepare_realism.py); knob values in provenance.realism.",
            ],
        },
    }
    (args.output / "recording.native.json").write_text(
        json.dumps(recording, separators=(",", ":"))
    )
    print(
        json.dumps(
            {
                "completed": True,
                "events": len(adapter.events),
                "score": last["score"],
                "seconds": frames / 25,
                "halftime": halfway,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
