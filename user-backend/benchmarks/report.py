"""Render concise, shareable results from standalone benchmark JSON."""
import argparse
import html
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from benchmarks.cases import cases
from benchmarks.correctness import FIXTURE, expected_trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--performance', type=Path, default=Path('.local/benchmarks/performance'))
    parser.add_argument('--agents', type=Path, default=Path('.local/benchmarks/agents-initial/report.json'))
    parser.add_argument('--output', type=Path, default=Path('.local/benchmarks/report'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    perf = json.loads((args.performance / 'report.json').read_text())
    (args.output / 'performance.json').write_text(json.dumps(perf, indent=2)+'\n')
    measured = [r for r in perf['cases'] if r['status'] == 'measured']
    lines = ['# Measured filter results', '',
             f"Recorded {datetime.now(ZoneInfo('Australia/Brisbane')).date()}. Native {perf['machine']}, Python {perf['python']}, {perf['logical_cpus']} logical CPUs. Single-process algorithm; no DB, model, network or viewer delivery in timings.", '',
             '![Event-processing latency](latency.svg)', '',
             '| Rules | Shape | p95 / event | Mean capacity | Peak RSS | Events measured |',
             '| ---: | --- | ---: | ---: | ---: | ---: |']
    for r in measured:
        lines.append(f"| {r['requested_rules']:,} | {r['workload']} | {r['latency']['p95_ms']:.3f} ms | {r['throughput_events_per_second']:.1f}/s | {r['peak_rss_mb']:.0f} MiB | {r['measured_events']:,}/{r['recording_events']:,} |")
    lines += ['', 'Larger tiers stop at the configured memory/time limit. **Unmeasured means unmeasured; no claim that 1m–100m unique filters fit or run.** Large tiers may time only a prefix; event counts above disclose this. Mean capacity is not a tail-latency guarantee.', '',
              '| Requested | Shape | Outcome | Rules registered before limit |', '| ---: | --- | --- | ---: |']
    for r in perf['cases']:
        if r['status'] != 'measured':
            lines.append(f"| {r['requested_rules']:,} | {r['workload']} | {r.get('reason', r['status'])} | {r.get('registered_rules', '—')} |")
    lines += ['', '## Offered event rates', '', 'These are queue models driven by measured service times, not real-time traffic tests.', '',
              '| 100k rule shape | Input | Estimated utilization | p95 processing + queue | Backlog after sample |',
              '| --- | ---: | ---: | ---: | ---: |']
    for r in measured:
        if r['requested_rules'] == 100000:
            for q in r['arrival_models']:
                lines.append(f"| {r['workload']} | {q['events_per_second']}/s | {q['utilization']:.0%} | {q['p95_response_ms']:.2f} ms | {q['backlog_after_sample_ms']:.2f} ms |")
    spread_path = Path('.local/benchmarks/spread/report.json')
    if spread_path.exists():
        spread = json.loads(spread_path.read_text())
        (args.output / 'spread.json').write_text(json.dumps(spread, indent=2)+'\n')
        lines += ['', '## Whole-match sampling at 100k filters', '',
                  'A fixed-seed permutation samples both halves rather than only the opening minutes. These are independent unique-ID events; this is not a chronological replay. Small sample sizes and GC/OS pauses limit precision.', '',
                  '| Shape | Events sampled | p95 / event | p99 / event | Maximum | Mean capacity |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |']
        for r in spread['cases']:
            if r['status'] == 'measured':
                lines.append(f"| {r['workload']} | {r['measured_events']:,} | {r['latency']['p95_ms']:.2f} ms | {r['latency']['p99_ms']:.2f} ms | {r['latency']['max_ms']:.2f} ms | {r['throughput_events_per_second']:.1f}/s |")
        selective = next(r for r in spread['cases'] if r['workload'] == 'selective' and r['status'] == 'measured')
        q = next(q for q in selective['arrival_models'] if q['events_per_second'] == 100)
        lines += ['', f"At 100 input events/s, selective filters average {q['utilization']:.0%} utilization, but measured service-time spikes raise modeled p95 queue-plus-processing latency to **{q['p95_response_ms']:.1f} ms**. Dense overlapping filters cannot sustain 5/s. [Raw whole-match samples](spread.json)."]
    lines += ['', 'The index performs at most 64 probes for a new event, **then evaluates every candidate**. At 100k rules, selective and overlapping candidate counts explain the difference; time-only filters all share one bucket. This implementation needs further work for dense overlapping demand.', '',
              'Sharing 100 distinct rules among 100k, 1m, 10m or 100m viewers does not add filter computation. This is an architectural arithmetic model, not an allocation or delivery test of those viewers.']
    reads_path = args.performance / 'value-reads.json'
    if reads_path.exists():
        reads = json.loads(reads_path.read_text())
        (args.output / 'value-reads.json').write_text(json.dumps(reads, indent=2)+'\n')
        lines += ['', f"Cached reads: **{reads['measured_reads']:,} lookups across {reads['registered_rules']:,} filters**, averaging **{reads['mean_ns_per_read']/1000:.3f} μs/read** ({reads['reads_per_second']:,.0f}/s). Includes the Python ID-selection loop and value access; excludes serialization and delivery."]
    full_path = Path('.local/benchmarks/full-match.json')
    if full_path.exists():
        full = json.loads(full_path.read_text())
        (args.output / 'full-match.json').write_text(json.dumps(full, indent=2)+'\n')
        lines += ['', f"Full-match cross-check: **{full['rules_checked']} generated rules passed** independent reference totals over **{full['deliveries']:,} deliveries**."]
    if args.agents.exists():
        agent = json.loads(args.agents.read_text())
        (args.output / 'agents.json').write_text(json.dumps(agent, indent=2)+'\n')
        gold, rows = agent['gold'], agent.get('agents', [])
        lines += ['', '## Correctness and model understanding', '',
                  f"**Gold rules: {sum(r['ok'] for r in gold)}/{len(gold)} passed** all 35 delivery prefixes and late backfill against explicit hand-authored contributions. These are not answers generated by the model."]
        if rows:
            strict = sum(r['ok'] for r in rows)
            different = sum(r.get('reason') == 'different_constraints' for r in rows)
            values_wrong = sum(r.get('reason') == 'wrong_event_value' for r in rows)
            lines += ['', f"**Real agents: {strict}/{len(rows)} strict passes.** {different} additional cases produced the correct fixture values but different constraints; {values_wrong} produced a wrong value during replay. Remaining failures include status mismatches/timeouts. A redundant inferred team predicate can explain some constraint differences; these are retained for review rather than silently accepted.", '',
                      '| Prompt quality | Strict pass | Total |', '| --- | ---: | ---: |']
            for quality in ('clear', 'average', 'messy', 'ambiguous_or_unsupported'):
                selected = [r for r in rows if r.get('quality') == quality]
                lines.append(f"| {quality} | {sum(r['ok'] for r in selected)} | {len(selected)} |")
            stat_rows = [r for r in rows if r['id'].startswith('stat-')]
            negative_rows = [r for r in rows if r['id'].startswith('negative-')]
            lines += ['', f"Of the **100 stat prompts**, {sum(r['ok'] for r in stat_rows)} passed exactly. The **12 negative prompts** passed {sum(r['ok'] for r in negative_rows)}. Failed requests are not silently replaced with fixture answers."]
            reasons = Counter(r.get('reason', 'unknown') for r in rows if not r['ok'])
            lines += ['', 'Failure categories: ' + ', '.join(f'`{key}`: {value}' for key, value in sorted(reasons.items())) + '.', '',
                      'This is one model run with bounded timeouts, not proof of language-understanding reliability. No gold expectations were supplied to the agent; only the normal match/team/player context. The repair harness checks the generated rule against the agent-defined goal, so a wrongly understood goal can still pass its internal validation.', '',
                      '[All agent results](agents.json) · [Cases and expected timelines](cases.json)']
    raw = json.loads(FIXTURE.read_text())['events']
    exported = [{**c, **({'expected_trace': expected_trace(c, raw)} if 'expected_rule' in c else {})} for c in cases()]
    (args.output / 'cases.json').write_text(json.dumps(exported, indent=2)+'\n')
    lines += ['', '[Run the harness](../README.md) · [Raw performance results](performance.json)', '']
    (args.output / 'README.md').write_text('\n'.join(lines))
    # Log-scaled bar plot keeps both selective and worst-case measurements readable.
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="820" height="430" viewBox="0 0 820 430">',
           '<rect width="820" height="430" fill="#131b23"/>',
           '<g font-family="system-ui,sans-serif" fill="#eef3f7">',
           '<text x="28" y="36" font-size="22">Time to process one event</text>',
           '<text x="28" y="61" font-size="12" fill="#afbbc6">p95 milliseconds · log scale · measured prefixes · lower is better</text>']
    def x(value):
        return 220 + (math.log10(max(value,.1)) + 1) / 4 * 540
    for tick in (.1, 1, 10, 100, 1000):
        px = x(tick)
        svg += [f'<path d="M{px} 90V365" stroke="#33414d"/>', f'<text x="{px}" y="390" text-anchor="middle" font-size="11">{tick:g} ms</text>']
    for index, r in enumerate(measured):
        y = 104 + index * 32
        colour = '#87dcab' if r['workload'] == 'selective' else '#efb179'
        label = html.escape(f"{r['requested_rules']:,} · {r['workload']}")
        end = x(r['latency']['p95_ms'])
        svg += [f'<text x="28" y="{y+4}" font-size="12">{label}</text>',
                f'<rect x="220" y="{y-10}" width="{max(2,end-220)}" height="16" rx="3" fill="{colour}"/>',
                f'<text x="{end+8}" y="{y+3}" font-size="11">{r["latency"]["p95_ms"]:.2f}</text>']
    svg += ['</g></svg>']
    (args.output / 'latency.svg').write_text('\n'.join(svg))


if __name__ == '__main__':
    main()
