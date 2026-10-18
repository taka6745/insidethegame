#!/usr/bin/env python3
"""Validate an actual export: files, identities, clocks, units and pass references."""

import argparse
import gzip
import hashlib
import json
import math
import subprocess
from collections import Counter
from pathlib import Path


def rows(path):
    with gzip.open(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def verify(folder):
    summary = json.loads((folder / "summary.json").read_text())
    for name, info in summary["files"].items():
        path = folder / name
        with path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        assert path.stat().st_size == info["bytes"] and digest == info["sha256"], name
    frames = touches = 0
    previous = None
    previous_match = None
    intervals = Counter()
    match_intervals = Counter()
    in_play_frames = 0
    phases = {}
    player_rows = 0
    for row in rows(folder / "raw.jsonl.gz"):
        assert all(
            math.isfinite(v)
            for k in ("ball_position_m", "ball_velocity_mps")
            for v in row[k]
        )
        if row["kind"] == "touch":
            touches += 1
            assert row["player"][0] in (0, 1)
            continue
        frames += 1
        if previous is not None:
            dt = row["physics_ms"] - previous
            assert dt > 0, "Non-increasing physics clock"
            intervals[dt] += 1
        previous = row["physics_ms"]
        if previous_match is not None:
            match_intervals[row["match_ms"] - previous_match] += 1
        previous_match = row["match_ms"]
        in_play_frames += bool(row["in_play"])
        phases.setdefault(row["phase"], row["match_ms"])
        identities = {(p["team"], p["id"]) for p in row["players"]}
        assert len(identities) == len(row["players"]) == 22
        player_rows += len(row["players"])
        for p in row["players"]:
            assert all(
                math.isfinite(v) for k in ("position_m", "velocity_mps") for v in p[k]
            )
            assert -80 < p["position_m"][0] < 80 and -60 < p["position_m"][1] < 60
    events = list(rows(folder / "events.jsonl.gz"))
    by_id = {e["id"]: e for e in events}
    assert len(by_id) == len(events)
    passes = json.loads((folder / "passes.json").read_text())
    for p in passes:
        assert by_id[p["pass_id"]]["type"] == "pass"
        assert by_id[p["source_touch_id"]]["type"] == "ball_touch"
        assert p["duration_s"] >= 0
        assert p["flight_path_m"] + 1e-6 >= p["displacement_m"]
        assert math.isclose(p["launch_speed_kmh"], p["launch_speed_mps"] * 3.6)
        assert p["completed"] is (
            True
            if p["outcome"] == "completed"
            else None
            if p["outcome"] == "unresolved_at_export_end"
            else False
        )
    assert frames == summary["frames"] and touches == summary["touches"]
    assert player_rows == summary["player_rows"]
    assert len(passes) == summary["event_counts"].get("pass", 0)
    if (folder / "observations.jsonl.gz").exists():
        assert (
            sum(1 for _ in rows(folder / "observations.jsonl.gz"))
            == summary["agent_steps"]
        )
    result = {
        "game": folder.name,
        "frames": frames,
        "player_rows": player_rows,
        "touches": touches,
        "passes": len(passes),
        "frame_intervals_ms": dict(intervals),
        "match_intervals_ms": dict(match_intervals),
        "in_play_physics_seconds": in_play_frames / 100,
        "first_phase_match_ms": phases,
    }
    print(json.dumps(result))
    return result


def verify_render(folder):
    report = json.loads((folder / "render.json").read_text())
    assert report["completed"], report.get("error")
    assert report["non_unit_clock_advances"] == 0
    assert (
        report["in_play_physics_seconds"] >= report["target_physics_play_seconds"] - 0.1
    )
    assert report["match_clock_seconds"] * 1000 >= report["target_match_clock_ms"]
    if report["target_physics_play_seconds"] >= 5400:
        assert {1, 2}.issubset(report["phases"]), "Missing a half"
    count = 0
    previous = None
    with (folder / "frame-times.jsonl").open() as f:
        for line in f:
            row = json.loads(line)
            assert row["frame"] == count
            assert math.isclose(row["video_seconds"], count / report["fps"])
            if previous:
                assert row["physics_ms"] > previous["physics_ms"]
                assert row["match_ms"] >= previous["match_ms"]
            previous = row
            count += 1
    assert count == report["video_frames"]
    assert previous["match_ms"] == round(report["match_clock_seconds"] * 1000)
    video = None
    if "graphics_renderer" in report:
        video = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-count_packets",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,codec_name,avg_frame_rate,nb_read_packets:format=duration,size",
                    "-of",
                    "json",
                    str(folder / "match.mp4"),
                ]
            )
        )
        stream = video["streams"][0]
        assert (stream["width"], stream["height"]) == (
            report["width"],
            report["height"],
        )
        assert int(stream["nb_read_packets"]) == count
        numerator, denominator = map(int, stream["avg_frame_rate"].split("/"))
        assert math.isclose(numerator / denominator, report["fps"])
        assert abs(float(video["format"]["duration"]) - report["video_seconds"]) < 0.1
    telemetry = verify(folder / "data")
    assert set(telemetry["match_intervals_ms"]).issubset({0, 10})
    assert telemetry["in_play_physics_seconds"] == report["in_play_physics_seconds"]
    assert set(telemetry["first_phase_match_ms"]) == set(report["phases"])
    if report["target_physics_play_seconds"] >= 5400:
        assert telemetry["first_phase_match_ms"][2] >= report["halftime_match_ms"]
    result = {
        "telemetry": telemetry,
        "video": video,
        "mapped_frames": count,
    }
    (folder / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if (args.output / "render.json").exists():
        verify_render(args.output)
        return
    games = sorted(args.output.glob("game-*"))
    assert games, "No game exports found"
    results = [verify(folder) for folder in games]
    report = json.loads((args.output / "benchmark.json").read_text())
    if report["branch_test"]:
        assert report["branch_test"]["exact_replay"]
        assert report["branch_test"]["intervention_changes_trajectory"]
    (args.output / "validation.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
