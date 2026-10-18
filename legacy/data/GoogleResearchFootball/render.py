#!/usr/bin/env python3
"""Render real-duration AI-vs-AI play and export the same world's native telemetry."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from run import UPSTREAM, Export, dump, engine


def make_match(seed, fps, width, render):
    import gfootball.scenarios
    from gfootball.env import create_environment

    gfootball.scenarios.__path__.append(str(Path(__file__).resolve().parent))
    return create_environment(
        env_name="full_match",
        representation="raw",
        number_of_left_players_agent_controls=1,
        number_of_right_players_agent_controls=1,
        render=render,
        write_video=False,
        other_config_options={
            "action_set": "v2",
            "game_engine_random_seed": seed,
            "real_time": False,
            "physics_steps_per_frame": 100 // fps,
            "render_resolution_x": width,
            "render_resolution_y": width * 9 // 16,
            "match_duration": 4.75,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--seconds",
        type=int,
        default=5400,
        help="Actual in-play physics seconds, not an accelerated scoreboard",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fps", type=int, choices=(10, 20, 25, 50), default=25)
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument(
        "--no-video",
        action="store_true",
        help="Validate long-match clocks and halftime headlessly",
    )
    parser.add_argument("--max-wall-hours", type=float, default=7.5)
    args = parser.parse_args()
    if args.seconds <= 0 or args.width < 320 or args.width % 32:
        parser.error("Use positive seconds and a width divisible by 32")
    args.output.mkdir(parents=True, exist_ok=False)
    data = args.output / "data"
    data.mkdir()
    checkpoints = args.output / "checkpoints"
    checkpoints.mkdir()
    os.environ.setdefault("GRF_HIDDEN_WINDOW", "1")
    started = time.perf_counter()
    env = make_match(args.seed, args.fps, args.width, not args.no_video)
    native = engine(env)
    assert abs(native.game_config.match_duration - 4.75) < 1e-6, (
        "Build render.patch first"
    )
    native.drain_telemetry()
    native.telemetry_enabled = True
    writer = Export(data, public_observations=False)
    # Use the native step API: one rendered frame per physics block, including dead play.
    # The stock Python wrapper skips dead-play frames and copies large RGB arrays repeatedly.
    from gfootball.env.football_action_set import action_builtin_ai

    for left in (True, False):
        native.perform_action(action_builtin_ai._backend_action, left, 0)
    process = None
    encoder_log = None
    frames = 0
    active_ticks = 0
    clock_ticks = 0
    phases = set()
    last = None
    last_report = 0.0
    next_checkpoint = 0
    clock_errors = 0
    start_clock_ms = None
    target_clock_ms = None
    frame_times = (args.output / "frame-times.jsonl").open("w")
    metadata = {
        "synthetic": True,
        "upstream_commit": UPSTREAM,
        "seed": args.seed,
        "width": args.width,
        "height": args.width * 9 // 16,
        "fps": args.fps,
        "target_physics_play_seconds": args.seconds,
        "clock_rate": 1,
        "halftime_match_ms": 2700000,
        "native_step_api": True,
        "note": "Match clock pauses during restarts. Native dead-play time jumps remain explicit in telemetry and frame timestamps.",
        "patch_sha256": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in ("telemetry.patch", "render.patch")
        },
        "completed": False,
    }
    dump(args.output / "render.json", metadata)
    init_seconds = time.perf_counter() - started
    if not args.no_video:
        import ctypes

        gl = ctypes.CDLL("/System/Library/Frameworks/OpenGL.framework/OpenGL")
        gl.glGetString.restype = ctypes.c_char_p
        renderer_name = gl.glGetString(0x1F01)
        metadata["graphics_renderer"] = (
            renderer_name.decode()
            if renderer_name
            else "macOS native OpenGL (SDL accelerated context)"
        )
        print("Graphics renderer:", metadata["graphics_renderer"], flush=True)
    if not args.no_video:
        encoder_log = (args.output / "ffmpeg.log").open("w")
        process = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-nostdin",
                "-f",
                "rawvideo",
                "-pixel_format",
                "rgb24",
                "-video_size",
                f"{args.width}x{args.width * 9 // 16}",
                "-framerate",
                str(args.fps),
                "-i",
                "pipe:0",
                "-vf",
                "vflip",
                "-an",
                "-c:v",
                "hevc_videotoolbox",
                "-allow_sw",
                "0",
                "-b:v",
                "20M",
                "-tag:v",
                "hvc1",
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(args.fps * 2),
                "-movflags",
                "+frag_keyframe+empty_moov+default_base_moof",
                str(args.output / "match.partial.mp4"),
            ],
            stdin=subprocess.PIPE,
            stderr=encoder_log,
        )
    loop_start = time.perf_counter()
    failure = None
    try:
        while True:
            native.step()
            batch = list(native.drain_telemetry())
            for raw in batch:
                writer.consume(raw)
                row = writer.last
                if row is None or '"kind":"touch"' in raw:
                    continue
                if start_clock_ms is None:
                    start_clock_ms = row["match_ms"] - (10 if row["in_play"] else 0)
                    target_clock_ms = start_clock_ms + args.seconds * 1000
                phases.add(row["phase"])
                if row["in_play"]:
                    active_ticks += 1
                if last:
                    dm = row["match_ms"] - last["match_ms"]
                    if dm:
                        clock_ticks += 1
                        if dm != 10:
                            clock_errors += 1
                last = row
            frames += 1
            if process:
                rgb = native.get_frame()
                assert len(rgb) == args.width * (args.width * 9 // 16) * 3, (
                    "Wrong native framebuffer size"
                )
                if frames == args.fps:
                    import cv2
                    import numpy as np

                    picture = np.frombuffer(rgb, dtype=np.uint8).reshape(
                        args.width * 9 // 16, args.width, 3
                    )[::-1]
                    cv2.imwrite(
                        str(args.output / "preview.png"),
                        cv2.cvtColor(picture, cv2.COLOR_RGB2BGR),
                    )
                process.stdin.write(rgb)
            frame_times.write(
                json.dumps(
                    {
                        "frame": frames - 1,
                        "video_seconds": (frames - 1) / args.fps,
                        "physics_ms": last["physics_ms"],
                        "match_ms": last["match_ms"],
                    }
                )
                + "\n"
            )
            if last["match_ms"] >= next_checkpoint:
                checkpoint = native.get_state("")
                (checkpoints / f"{frames:07d}.bin").write_bytes(checkpoint)
                dump(
                    checkpoints / f"{frames:07d}.json",
                    {
                        "video_frames": frames,
                        "physics_ms": last["physics_ms"],
                        "match_ms": last["match_ms"],
                        "score": last["score"],
                    },
                )
                next_checkpoint = last["match_ms"] + 300000
            elapsed = time.perf_counter() - loop_start
            if elapsed - last_report >= 15 or last["match_ms"] >= target_clock_ms:
                progress = {
                    "frames": frames,
                    "match_seconds": last["match_ms"] / 1000,
                    "in_play_physics_seconds": active_ticks / 100,
                    "processed_physics_seconds": writer.frames / 100,
                    "video_seconds": frames / args.fps,
                    "elapsed_seconds": elapsed,
                    "render_fps": frames / elapsed,
                    "score": last["score"],
                    "eta_seconds": max(0, (target_clock_ms - last["match_ms"]) / 1000)
                    / (last["match_ms"] / 1000 / elapsed)
                    if last["match_ms"]
                    else None,
                }
                dump(args.output / "progress.json", progress)
                print(json.dumps(progress), flush=True)
                last_report = elapsed
            if last["match_ms"] >= target_clock_ms:
                break
            if time.perf_counter() - started > args.max_wall_hours * 3600:
                raise TimeoutError(
                    "Wall-time budget reached; partial video and checkpoints are retained"
                )
        assert clock_errors == 0, f"{clock_errors} accelerated clock increments found"
        assert active_ticks / 100 >= args.seconds - 0.1, "Not enough real physics play"
        if args.seconds >= 5400:
            assert 1 in phases and 2 in phases, "Both halves were not simulated"
    except BaseException as exc:
        failure = repr(exc)
        raise
    finally:
        frame_times.close()
        if process:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
            code = process.wait(timeout=120)
            encoder_log.close()
            if code:
                failure = f"ffmpeg exited {code}; inspect ffmpeg.log"
        summary = writer.close()
        dump(data / "summary.json", summary)
        metadata.update(
            completed=failure is None,
            error=failure,
            video_frames=frames,
            video_seconds=frames / args.fps,
            processed_physics_seconds=writer.frames / 100,
            in_play_physics_seconds=active_ticks / 100,
            match_clock_seconds=last["match_ms"] / 1000,
            start_match_clock_ms=start_clock_ms,
            target_match_clock_ms=target_clock_ms,
            clock_advances_checked=clock_ticks,
            non_unit_clock_advances=clock_errors,
            phases=sorted(phases),
            score=last["score"],
            initialization_seconds=init_seconds,
            total_wall_seconds=time.perf_counter() - started,
            data_summary=summary,
        )
        dump(args.output / "render.json", metadata)
        env.close()
        if failure is None and process:
            (args.output / "match.partial.mp4").rename(args.output / "match.mp4")
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
