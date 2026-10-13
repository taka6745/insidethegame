#!/usr/bin/env python3
"""AI-vs-AI export, paired headless benchmark and deterministic branch check."""

import argparse
import csv
import gzip
import hashlib
import json
import math
import platform
import statistics
import time
from pathlib import Path

from events import FUNCTIONS, Events, norm

UPSTREAM = "3d9e754720a95621bba6475c4d3b0d56fe919014"


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def make_env(seed):
    from gfootball.env import create_environment

    return create_environment(
        env_name="11_vs_11_stochastic",
        representation="raw",
        number_of_left_players_agent_controls=1,
        number_of_right_players_agent_controls=1,
        render=False,
        write_video=False,
        other_config_options={
            "action_set": "v2",
            "game_engine_random_seed": seed,
            "real_time": False,
        },
    )


def engine(env):
    return env.unwrapped._env._env


def line(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n"


class Export:
    def __init__(self, folder, public_observations=True):
        self.folder = folder
        self.raw = gzip.open(folder / "raw.jsonl.gz", "wt", compresslevel=1)
        self.observations = (
            gzip.open(folder / "observations.jsonl.gz", "wt", compresslevel=1)
            if public_observations
            else None
        )
        self.event_file = gzip.open(folder / "events.jsonl.gz", "wt", compresslevel=1)
        self.player_file = gzip.open(
            folder / "players.csv.gz", "wt", compresslevel=1, newline=""
        )
        self.ball_file = gzip.open(
            folder / "ball.csv.gz", "wt", compresslevel=1, newline=""
        )
        self.events = Events(lambda r: self.event_file.write(line(r)))
        self.player_writer = csv.writer(self.player_file)
        self.ball_writer = csv.writer(self.ball_file)
        self.player_writer.writerow(
            [
                "physics_ms",
                "match_ms",
                "team",
                "index",
                "id",
                "x_m",
                "y_m",
                "z_m",
                "vx_mps",
                "vy_mps",
                "vz_mps",
                "speed_mps",
                "speed_kmh",
                "acceleration_mps2",
                "distance_in_play_m",
                "heading_degrees",
                "facing_x",
                "facing_y",
                "body_facing_x",
                "body_facing_y",
                "active",
                "has_card",
                "tired_factor",
                "role",
                "function",
                "has_possession",
                "possession_ms",
                "time_to_ball_ms",
                "nearest_opponent_m",
                "opponents_within_3m",
                "discontinuity",
            ]
        )
        self.ball_writer.writerow(
            [
                "physics_ms",
                "match_ms",
                "x_m",
                "y_m",
                "z_m",
                "vx_mps",
                "vy_mps",
                "vz_mps",
                "speed_mps",
                "speed_kmh",
                "horizontal_speed_mps",
                "acceleration_mps2",
                "direction_degrees",
                "owner_team",
                "owner_index",
                "in_play",
                "game_mode",
                "left_score",
                "right_score",
                "discontinuity",
            ]
        )
        self.frames = 0
        self.touches = 0
        self.previous = None
        self.prev_players = {}
        self.distance = {}
        self.max_player_speed = 0
        self.max_ball_speed = 0
        self.first_ms = None
        self.last = None

    def observation(self, step, observations, reward, done):
        record = {
            "agent_step": step,
            "actions": [19, 19],
            "observations": observations,
            "reward": reward,
            "done": done,
        }
        self.observations.write(
            json.dumps(record, default=lambda v: v.tolist(), allow_nan=False) + "\n"
        )

    def consume(self, raw):
        self.raw.write(raw + "\n")
        r = json.loads(raw)
        self.events.consume(r)
        if r["kind"] == "touch":
            self.touches += 1
            return
        self.frames += 1
        self.last = r
        if self.first_ms is None:
            self.first_ms = r["physics_ms"]
        dt = (
            (r["physics_ms"] - self.previous["physics_ms"]) / 1000
            if self.previous
            else 0
        )
        bv = r["ball_velocity_mps"]
        bs = norm(bv)
        self.max_ball_speed = max(self.max_ball_speed, bs)
        jump = bool(
            self.previous
            and (
                not self.previous["in_play"]
                or not r["in_play"]
                or norm(
                    [
                        a - b
                        for a, b in zip(
                            r["ball_position_m"], self.previous["ball_position_m"]
                        )
                    ]
                )
                > max(bs, norm(self.previous["ball_velocity_mps"])) * dt + 1
            )
        )
        ba = (
            (bs - norm(self.previous["ball_velocity_mps"])) / dt
            if dt and not jump
            else None
        )
        self.ball_writer.writerow(
            [
                r["physics_ms"],
                r["match_ms"],
                *r["ball_position_m"],
                *bv,
                bs,
                bs * 3.6,
                norm(bv[:2]),
                ba,
                math.degrees(math.atan2(bv[1], bv[0])),
                *r["owner"],
                r["in_play"],
                r["game_mode"],
                *r["score"],
                jump,
            ]
        )
        for p in r["players"]:
            k = (p["team"], p["id"])
            prev = self.prev_players.get(k)
            speed = norm(p["velocity_mps"])
            self.max_player_speed = max(self.max_player_speed, speed)
            discontinuity = bool(
                prev
                and (
                    not r["in_play"]
                    or not self.previous["in_play"]
                    or norm(
                        [a - b for a, b in zip(p["position_m"], prev["position_m"])]
                    )
                    > max(speed, norm(prev["velocity_mps"])) * dt + 0.3
                )
            )
            acceleration = (
                (speed - norm(prev["velocity_mps"])) / dt
                if dt and prev and not discontinuity
                else None
            )
            self.distance.setdefault(k, 0.0)
            if (
                dt
                and prev
                and r["in_play"]
                and self.previous["in_play"]
                and p["active"]
                and not discontinuity
            ):
                self.distance[k] += (speed + norm(prev["velocity_mps"])) * 0.5 * dt
            opponents = [
                norm([a - b for a, b in zip(p["position_m"][:2], q["position_m"][:2])])
                for q in r["players"]
                if q["team"] != p["team"] and q["active"]
            ]
            self.player_writer.writerow(
                [
                    r["physics_ms"],
                    r["match_ms"],
                    p["team"],
                    p["index"],
                    p["id"],
                    *p["position_m"],
                    *p["velocity_mps"],
                    speed,
                    speed * 3.6,
                    acceleration,
                    self.distance[k],
                    math.degrees(
                        math.atan2(p["velocity_mps"][1], p["velocity_mps"][0])
                    ),
                    *p["facing"][:2],
                    *p["body_facing"][:2],
                    p["active"],
                    p["has_card"],
                    p["tired_factor"],
                    p["role"],
                    FUNCTIONS[p["function"]],
                    p["has_possession"],
                    p["possession_ms"],
                    p["time_to_ball_ms"],
                    min(opponents) if opponents else None,
                    sum(d <= 3 for d in opponents),
                    discontinuity,
                ]
            )
            self.prev_players[k] = p
        self.previous = r

    def close(self):
        self.events.finish()
        for f in (
            self.raw,
            self.event_file,
            self.player_file,
            self.ball_file,
            self.observations,
        ):
            if f is not None:
                f.close()
        dump(self.folder / "passes.json", self.events.passes)
        result = {
            "frames": self.frames,
            "player_rows": self.frames * 22,
            "touches": self.touches,
            "score": self.last["score"],
            "physics_duration_s": (self.last["physics_ms"] - self.first_ms) / 1000,
            "match_clock_end_s": self.last["match_ms"] / 1000,
            "event_counts": dict(self.events.counts),
            "max_player_speed_mps": self.max_player_speed,
            "max_ball_speed_mps": self.max_ball_speed,
            "completed_passes": sum(p["completed"] is True for p in self.events.passes),
            "unresolved_passes": sum(
                p["completed"] is None for p in self.events.passes
            ),
            "files": {
                p.name: {
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in self.folder.iterdir()
                if p.is_file()
            },
        }
        return result


def branch_test(env, folder):
    native = engine(env)
    native.drain_telemetry()
    native.telemetry_enabled = True
    # Save at a confirmed possession, early enough to have rollout room.
    obs = env.observation()
    steps = 0
    while (obs[0]["ball_owned_team"] < 0 or steps < 20) and steps < 500:
        obs, _, done, _ = env.step([19, 19])
        native.drain_telemetry()
        steps += 1
        if done:
            raise RuntimeError("Episode ended before branch point")
    if obs[0]["ball_owned_team"] < 0:
        raise RuntimeError("No confirmed owner found for the branch intervention")
    state = env.get_state()
    (folder / "checkpoint.bin").write_bytes(state)

    def rollout(name, intervene=False):
        env.set_state(state)
        native.drain_telemetry()
        records = []
        actions = []
        team = int(obs[0]["ball_owned_team"])
        for t in range(100):
            a = [19, 19]
            if intervene and t < 10:
                a[team] = 12 if t >= 2 else 5
            _, _, done, _ = env.step(a)
            actions.append(a)
            records.extend(list(native.drain_telemetry()))
            if done:
                break
        with gzip.open(folder / (name + ".jsonl.gz"), "wt", compresslevel=1) as f:
            for r in records:
                f.write(r + "\n")
        dump(folder / (name + "-actions.json"), actions)
        frames = [json.loads(r) for r in records if json.loads(r)["kind"] == "frame"]
        return {
            "sha256": hashlib.sha256("\n".join(records).encode()).hexdigest(),
            "records": len(records),
            "last_ball_position_m": frames[-1]["ball_position_m"],
            "score": frames[-1]["score"],
        }

    a = rollout("original")
    b = rollout("repeated")
    c = rollout("alternative", True)
    result = {
        "snapshot_bytes": len(state),
        "original": a,
        "repeated": b,
        "alternative": c,
        "exact_replay": a["sha256"] == b["sha256"],
        "intervention_changes_trajectory": a["sha256"] != c["sha256"],
        "intervention": "Ball-owning team: two right-direction actions, eight shot actions, then built-in AI.",
        "rollout_agent_steps": 100,
        "external_controller": "stateless built-in-AI delegation",
    }
    dump(folder / "branch-test.json", result)
    assert result["exact_replay"], "Identical replay differs"
    assert result["intervention_changes_trajectory"], (
        "Intervention did not change trajectory"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-steps",
        type=int,
        default=0,
        help="0 completes the scenario; positive is a smoke test",
    )
    parser.add_argument("--skip-branch", action="store_true")
    args = parser.parse_args()
    if args.games < 1 or args.max_steps < 0:
        parser.error("games must be positive; max-steps must be nonnegative")
    args.output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    env = make_env(args.seed)
    cold = time.perf_counter() - start
    native = engine(env)
    assert hasattr(native, "drain_telemetry"), "Build the instrumented image first"
    results = []
    for i in range(args.games):
        # Same seed and episode number for each baseline/export pair.
        for capture in (False, True):
            native.telemetry_enabled = False
            env.unwrapped._config["game_engine_random_seed"] = args.seed + i
            env.unwrapped._config["episode_number"] = 0
            t = time.perf_counter()
            env.reset()
            reset = time.perf_counter() - t
            native.drain_telemetry()
            native.telemetry_enabled = capture
            folder = args.output / f"game-{i + 1:02d}"
            writer = None
            if capture:
                folder.mkdir()
                writer = Export(folder)
            steps = 0
            t = time.perf_counter()
            done = False
            trajectory = hashlib.sha256()
            while not done:
                obs, reward, done, _ = env.step([19, 19])
                steps += 1
                trajectory.update(
                    json.dumps(
                        obs[0], sort_keys=True, default=lambda v: v.tolist()
                    ).encode()
                )
                if capture:
                    writer.observation(steps, obs, reward, done)
                    for raw in native.drain_telemetry():
                        writer.consume(raw)
                if args.max_steps and steps >= args.max_steps:
                    break
            summary = writer.close() if writer else {}
            elapsed = time.perf_counter() - t
            result = {
                "game": i + 1,
                "seed": args.seed + i,
                "mode": "verbose_export" if capture else "headless_no_export",
                "agent_steps": steps,
                "completed": done,
                "observation_sha256": trajectory.hexdigest(),
                "wall_seconds": elapsed,
                "reset_seconds": reset,
                "agent_steps_per_second": steps / elapsed,
                "score": [int(x) for x in obs[0]["score"]],
                **summary,
            }
            if writer:
                dump(folder / "summary.json", result)
            if capture:
                assert (
                    result["observation_sha256"] == results[-1]["observation_sha256"]
                ), "Telemetry changed the observed trajectory"
            results.append(result)
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in (
                            "game",
                            "mode",
                            "wall_seconds",
                            "agent_steps",
                            "score",
                        )
                    }
                ),
                flush=True,
            )
    branch = None
    if not args.skip_branch:
        native.telemetry_enabled = False
        env.reset()
        native.drain_telemetry()
        folder = args.output / "branch"
        folder.mkdir()
        branch = branch_test(env, folder)
        print("Branch test:", json.dumps(branch), flush=True)
    env.close()
    report = {
        "upstream_commit": UPSTREAM,
        "architecture": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cold_initialization_seconds": cold,
        "rendering": False,
        "telemetry_preserves_observed_trajectories": True,
        "physics_tick_ms": 10,
        "physics_ticks_per_agent_step": 10,
        "scenario": "11_vs_11_stochastic",
        "scenario_limit_agent_steps": 3000,
        "synthetic": True,
        "team_difficulty": {"left": 1.0, "right": 0.6},
        "coordinates": {
            "origin": "pitch centre",
            "pitch_m": [110, 72],
            "axes": "native engine x/y; z is height",
            "team_direction": "left attacks +x, right attacks -x; verify against scenario",
        },
        "patch_sha256": hashlib.sha256(
            Path("/work/telemetry.patch").read_bytes()
        ).hexdigest(),
        "note": "Scenario clock is accelerated; 3000 steps is not 90 minutes of physical motion. Includes wrapper, observation hashing and export work, excludes startup/reset from per-game timings.",
        "runs": results,
        "median_wall_seconds": {
            mode: statistics.median(
                r["wall_seconds"] for r in results if r["mode"] == mode
            )
            for mode in ("headless_no_export", "verbose_export")
        },
        "branch_test": branch,
    }
    dump(args.output / "benchmark.json", report)


if __name__ == "__main__":
    main()
