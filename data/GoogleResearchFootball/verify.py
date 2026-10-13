#!/usr/bin/env python3
"""Validate an actual export: files, identities, clocks, units and pass references."""

import argparse
import gzip
import hashlib
import json
import math
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
    intervals = Counter()
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
    result = dict(
        game=folder.name,
        frames=frames,
        player_rows=player_rows,
        touches=touches,
        passes=len(passes),
        frame_intervals_ms=dict(intervals),
    )
    print(json.dumps(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
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
