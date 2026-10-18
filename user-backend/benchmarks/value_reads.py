"""Measure cached per-viewer value reads separately from event computation."""
import argparse
import json
import time
from pathlib import Path

from backend.services.filter_engine import FilterEngine
from .performance import DEFAULT_RECORDING, generated_rule, load, peak_mb, templates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rules', type=int, default=100000)
    parser.add_argument('--reads', type=int, default=1000000)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--output', type=Path, default=Path('.local/benchmarks/performance/value-reads.json'))
    args = parser.parse_args()
    if not 1 <= args.rules <= 100000 or not 1 <= args.reads <= 100000000 or args.timeout <= 0:
        parser.error('Rules: 1..100k; reads: 1..100m; positive timeout')
    recording, events = load(DEFAULT_RECORDING)
    keys, engine, ids = templates(events), FilterEngine(), []
    started = time.perf_counter()
    for i in range(args.rules):
        result = engine.register(generated_rule(i, recording['match_id'], 'selective', keys))
        ids.append(result.calculation_id)
        if i % 1000 == 0 and time.perf_counter() - started > args.timeout:
            raise TimeoutError('Registration timeout')
    samples, reads = [], 0
    # Walk every stored rule ID with a coprime stride, not just one hot cache key.
    while reads < args.reads:
        count = min(10000, args.reads - reads)
        start = time.perf_counter_ns()
        for i in range(reads, reads + count):
            engine.get(ids[(i * 7919) % len(ids)]).value
        samples.append((time.perf_counter_ns() - start) / 1e9)
        reads += count
        if time.perf_counter() - started > args.timeout:
            break
    result = {'registered_rules': engine.count, 'requested_reads': args.reads, 'measured_reads': reads,
              'seconds': sum(samples), 'mean_ns_per_read': sum(samples) * 1e9 / reads,
              'reads_per_second': reads / sum(samples), 'peak_rss_mb': peak_mb(),
              'scope': 'Engine.get plus value access, ID lookup loop included; no subscribers, serialization or network'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
