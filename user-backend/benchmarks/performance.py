"""Standalone, bounded algorithm benchmark. No agents, DB, sockets or fan-out."""
import argparse
import gzip
import hashlib
import json
import math
import os
import platform
import random
import resource
import signal
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

from backend.adapters.events import OptaInspiredAdapter
from backend.models.rules import Rule
from backend.services.filter_engine import FilterEngine

DEFAULT_RECORDING = Path(__file__).resolve().parents[2] / "data-generation/recordings/grf-full-match.json.gz"


def peak_mb():
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024 * 1024 if sys.platform == "darwin" else 1024)


def load(path):
    with gzip.open(path, "rt") if path.suffix == ".gz" else path.open() as stream:
        recording = json.load(stream)
    return recording, [OptaInspiredAdapter().adapt(e) for e in recording["events"]]


def templates(events):
    return sorted({(e.event_type, e.player_id, e.period) for e in events})


def generated_rule(index, match_id, workload, keys):
    # Integer windows and actual player/event/period combinations, never a model.
    terms = []
    window = index
    if workload == "selective":
        window, key_index = divmod(index, len(keys))
        event_type, player_id, period = keys[key_index]
        terms = [{"field": field, "op": "eq", "value": value} for field, value in
                 (("event_type", event_type), ("player_id", player_id), ("period", period))]
    variant, window = divmod(window, 36_000_000)
    upper, lower = divmod(window, 6000)
    terms += [{"field": "match_time_seconds", "op": "gte" if variant % 2 == 0 else "gt", "value": lower},
              {"field": "match_time_seconds", "op": "lte", "value": 6001 + upper}]
    operation = "count" if variant < 2 else "sum"
    return Rule(match_id=match_id, predicates=terms, operation=operation,
                sum_field="distance_metres" if operation == "sum" else None)


def reference_total(rule, events):
    """Deliberately simple independent interpreter; excludes production match/contribution/index code."""
    latest = {}
    for e in events:
        key = (e.match_id, e.event_id)
        if key not in latest or e.revision > latest[key].revision:
            latest[key] = e
    total = Decimal(0)
    for e in latest.values():
        if e.deleted or e.match_id != rule.match_id:
            continue
        matches = True
        for p in rule.predicates:
            actual, wanted = getattr(e, p.field), p.value
            if actual is None:
                matches = False
                break
            passed = {"eq": lambda: actual == wanted, "in": lambda: actual in wanted,
                      "gt": lambda: actual > wanted, "gte": lambda: actual >= wanted,
                      "lt": lambda: actual < wanted, "lte": lambda: actual <= wanted}[p.op]()
            if not passed:
                matches = False
                break
        if matches:
            total += Decimal(str(1 if rule.operation == "count" else getattr(e, rule.sum_field) or 0))
    return float(total)


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)]


def arrival_model(samples, rate):
    # Replay the measured service times at fixed offered rates without sleeping.
    # This is a single-worker queue model, not a wall-clock load generator.
    finish, waits = 0., []
    for i, elapsed in enumerate(samples):
        arrival = i / rate
        finish = max(finish, arrival) + elapsed
        waits.append(finish - arrival)
    return {"events_per_second": rate, "utilization": rate * sum(samples) / len(samples),
            "p95_response_ms": percentile(waits, .95) * 1000,
            "max_response_ms": max(waits) * 1000,
            "backlog_after_sample_ms": max(0, finish - len(samples) / rate) * 1000}


def worker(args):
    recording, events = load(args.recording)
    keys = templates(events)
    if args.event_order == "spread":
        if len({(e.match_id, e.event_id) for e in events}) != len(events):
            raise ValueError("Spread sampling requires unique event IDs; keep correction feeds chronological")
        random.Random(20261018).shuffle(events)
    # Warm the Python path on a disposable engine; don't warm the measured history.
    warm = FilterEngine()
    warm.register(generated_rule(0, recording["match_id"], args.workload, keys))
    for event in events[:100]:
        warm.ingest(event)
    del warm
    baseline = peak_mb()
    engine, sampled = FilterEngine(), []
    started = time.perf_counter()
    result = {"workload": args.workload, "requested_rules": args.count, "status": "building", "baseline_mb": baseline, "event_order": args.event_order}

    def save(**kwargs):
        result.update(kwargs, peak_rss_mb=peak_mb())
        args.output.write_text(json.dumps(result))

    for i in range(args.count):
        rule = generated_rule(i, recording["match_id"], args.workload, keys)
        engine.register(rule)
        if i in {0, args.count // 4, args.count // 2, args.count - 1}:
            sampled.append(rule)
        if (i + 1) % 1000 == 0 or i + 1 == args.count:
            save(registered_rules=engine.count, build_seconds=time.perf_counter() - started)
            if peak_mb() >= args.memory_mb or time.perf_counter() - started >= args.build_timeout:
                save(status="build_limit", reason="memory" if peak_mb() >= args.memory_mb else "build_timeout")
                return
    assert engine.count == args.count, "Generated rules must really be unique"
    save(status="replaying", registered_rules=engine.count, build_seconds=time.perf_counter() - started)
    samples, candidates, probes, family_evaluations, time_probes = [], [], [], [], []
    replay_start = time.perf_counter()
    for event in events:
        start = time.perf_counter_ns()
        engine.ingest(event)
        elapsed = (time.perf_counter_ns() - start) / 1e9
        samples.append(elapsed)
        candidates.append(engine.last_candidate_count)
        probes.append(engine.last_index_probe_count)
        family_evaluations.append(engine.last_family_evaluation_count)
        time_probes.append(engine.last_time_probe_count)
        if time.perf_counter() - replay_start > args.replay_timeout:
            break
    replay_wall = time.perf_counter() - replay_start
    prefix = events[:len(samples)]
    for rule in sampled:
        assert engine.get(rule.calculation_id).value == reference_total(rule, prefix), "Independent reference mismatch"
    values = {"mean_ms": 1000 * sum(samples) / len(samples), "p50_ms": 1000 * percentile(samples, .5),
              "p95_ms": 1000 * percentile(samples, .95), "p99_ms": 1000 * percentile(samples, .99), "max_ms": 1000 * max(samples)}
    save(status="measured", recording_events=len(events), measured_events=len(samples),
         full_match=len(samples) == len(events), replay_wall_seconds=replay_wall,
         throughput_events_per_second=len(samples) / sum(samples), latency=values,
         candidates_mean=sum(candidates) / len(candidates), candidates_max=max(candidates),
         index_probes_max=max(probes), reference_checks=len(sampled),
         family_evaluations_mean=sum(family_evaluations) / len(family_evaluations),
         family_evaluations_max=max(family_evaluations), time_index_probes_max=max(time_probes),
         arrival_models=[arrival_model(samples, rate) for rate in (1, 5, 100)])


def rss_mb(pid):
    status = Path(f"/proc/{pid}/status")
    if sys.platform == "linux":
        try:
            for line in status.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        except FileNotFoundError:
            pass
        return 0
    result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    return int(result.stdout.strip() or "0") / 1024


def parent(args):
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "single-process FilterEngine.ingest only; no model, database, network, subscriber routing or serialization",
              "python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
              "logical_cpus": os.cpu_count(),
              "engine_sha256": hashlib.sha256(Path(__file__).resolve().parents[1].joinpath("backend/services/filter_engine.py").read_bytes()).hexdigest(), "recording_sha256": hashlib.sha256(args.recording.read_bytes()).hexdigest(),
              "time_index_sha256": hashlib.sha256(Path(__file__).resolve().parents[1].joinpath("backend/services/time_index.py").read_bytes()).hexdigest(),
              "memory_limit_mb": args.memory_mb, "build_timeout_seconds": args.build_timeout,
              "replay_timeout_seconds": args.replay_timeout, "cases": []}
    started = time.monotonic()
    for workload in args.workloads:
        prior_limit = None
        for count in args.sizes:
            path = args.output / f"{workload}-{count}.json"
            if prior_limit or time.monotonic() - started > args.suite_timeout:
                result = {"workload": workload, "requested_rules": count, "status": "unmeasured",
                          "reason": prior_limit or "suite_timeout"}
            else:
                command = [sys.executable, "-m", "benchmarks.performance", "--worker", "--count", str(count),
                           "--workload", workload, "--event-order", args.event_order, "--recording", str(args.recording), "--output", str(path),
                           "--memory-mb", str(args.memory_mb), "--build-timeout", str(args.build_timeout),
                           "--replay-timeout", str(args.replay_timeout)]
                with (args.output / f"{workload}-{count}.log").open("w") as log:
                    process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
                    deadline = min(started + args.suite_timeout,
                                   time.monotonic() + args.build_timeout + args.replay_timeout + 15)
                    reason = None
                    try:
                        while process.poll() is None:
                            # A parent watchdog bounds both RSS and wall time, including a slow single event.
                            mb = rss_mb(process.pid)
                            if mb > args.memory_mb or time.monotonic() > deadline:
                                reason = "memory_limit" if mb > args.memory_mb else "worker_timeout"
                                os.killpg(process.pid, signal.SIGKILL)
                                break
                            time.sleep(.1)
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                result = json.loads(path.read_text()) if path.exists() else {"workload": workload, "requested_rules": count}
                if reason or process.returncode:
                    result.update(status="unmeasured", reason=reason or "worker_error")
                if result.get("status") != "measured":
                    prior_limit = f"smaller tier {count} reached {result.get('reason', result.get('status'))}"
            path.write_text(json.dumps(result, indent=2) + "\n")
            report["cases"].append(result)
            print(f"{workload} {count:,}: {result['status']} {result.get('latency', {}).get('p95_ms', '')}", flush=True)
            (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    measured = [r for r in report["cases"] if r["status"] == "measured"]
    report["shared_viewer_model"] = [{"viewers": viewers, "distinct_filters": 100,
        "note": "Same 100 rules computed once, independent of viewer count. No subscriber objects allocated or delivery cost measured.",
        "measured_compute_p95_ms": next((r["latency"]["p95_ms"] for r in measured if r["requested_rules"] == 100 and r["workload"] == "selective"), None)}
        for viewers in (100_000, 1_000_000, 10_000_000, 100_000_000)]
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if any(r.get("reason") == "worker_error" for r in report["cases"]):
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, default=DEFAULT_RECORDING)
    parser.add_argument("--output", type=Path, default=Path(".local/benchmarks/performance"))
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000, 100000, 1000000, 10000000, 100000000])
    parser.add_argument("--build-timeout", type=float, default=30)
    parser.add_argument("--replay-timeout", type=float, default=20)
    parser.add_argument("--suite-timeout", type=float, default=300)
    parser.add_argument("--memory-mb", type=int, default=1024)
    parser.add_argument("--event-order", choices=["chronological", "spread"], default="chronological")
    parser.add_argument("--workloads", nargs="+", choices=["selective", "overlapping"], default=["selective", "overlapping"])
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--workload", choices=["selective", "overlapping"], default="selective")
    args = parser.parse_args()
    if min(args.sizes + [args.count, args.memory_mb, args.build_timeout, args.replay_timeout, args.suite_timeout]) <= 0:
        parser.error("Sizes and limits must be positive")
    args.sizes = sorted(set(args.sizes))
    worker(args) if args.worker else parent(args)


if __name__ == "__main__":
    main()
