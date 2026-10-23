"""Save an honest, separate agent improvement report; never replace old results."""
import argparse
import json
import statistics
from pathlib import Path


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))] if ordered else None


def summary(rows):
    seconds = [row['seconds'] for row in rows if 'seconds' in row]
    return (f"{sum(row['ok'] for row in rows)}/{len(rows)}", f"{statistics.median(seconds):.2f}" if seconds else '—',
            f"{percentile(seconds, .95):.2f}" if seconds else '—')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--quality', type=Path, required=True)
    parser.add_argument('--conversations', type=Path)
    parser.add_argument('--serial', type=Path)
    parser.add_argument('--output', type=Path, default=Path('.local/benchmarks/agents-improved'))
    args = parser.parse_args()
    baseline, quality = [json.loads(path.read_text()) for path in (args.baseline, args.quality)]
    # The first quality process started before the missing-metrics fix. A failed
    # request with no stage record has unknown call count, not a measured zero.
    for report in (baseline, quality):
        for row in report.get("agents", []):
            for turn in row.get("turns", []):
                if turn.get("status") == "failed" and not turn.get("stage_seconds"):
                    turn["model_calls"] = None
                    row["model_calls"] = None
    args.output.mkdir(parents=True, exist_ok=True)
    for name, report in [('baseline', baseline), ('quality', quality)]:
        (args.output / f'agents-improved-{name}.json').write_text(json.dumps(report, indent=2) + '\n')
    original = json.loads((args.output / 'agents.json').read_text())['agents']
    groups = [
        ('Original recorded mixed-quality stat requests', [r for r in original if r['id'].startswith('stat-')]),
        ('Same 100 requests after improvements', [r for r in baseline['agents'] if r['id'].startswith('stat-')]),
        ('Same 12 negative/ambiguous requests', [r for r in baseline['agents'] if r['id'].startswith('negative-')]),
        ('Separate 100 quality requests', [r for r in quality['agents'] if r['id'].startswith('quality-stat-')]),
        ('Quality cohort: original negatives', [r for r in quality['agents'] if r['id'].startswith('quality-negative-')]),
        ('Two-turn clarification conversations', [r for r in quality['agents'] if r['id'].startswith('conversation-')]),
    ]
    lines = ['# Agent interpretation improvements', '',
        'Measured with the configured local model through Microsoft Agent Framework. Original results and prompts remain unchanged.', '',
        '| Cohort | Exact passes | Median request seconds | p95 request seconds |',
        '| --- | ---: | ---: | ---: |']
    for label, rows in groups:
        count, median, p95 = summary(rows)
        lines.append(f'| {label} | {count} | {median} | {p95} |')
    lines += ['', 'Stat-request outcome breakdown:', '',
        '| Run | Exact | Wrong values | Different constraints | Timeout | Other non-ready |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for label, rows in (groups[0], groups[1], groups[3]):
        wrong = sum(row.get('reason') == 'wrong_event_value' for row in rows)
        different = sum(row.get('reason') == 'different_constraints' for row in rows)
        timed_out = sum(row.get('status') == 'failed' and row.get('seconds', 0) >= 44.9 for row in rows)
        other = sum(not row['ok'] for row in rows) - wrong - different - timed_out
        lines.append(f"| {label} | {sum(row['ok'] for row in rows)} | {wrong} | {different} | {timed_out} | {other} |")
    lines += ['', '## What changed', '',
        '- One model call defines the semantic goal; a typed compiler maps it to a rule without another model call.',
        '- The goal schema enumerates available event types and outcomes. Feed semantics distinguish headed contacts, shots/goals, and clock boundaries.',
        '- Ambiguous requests can ask a question and interpret the subsequent user reply with bounded conversation history.',
        '- All ready rules are checked against independently hand-authored event/revision weights and exact constraints. Gold answers never enter model prompts.', '',
        '## Limits', '',
        'These are single evaluation runs, not statistical accuracy guarantees. The two updated cohorts ran concurrently (four cases each), sharing a model service. Their latency includes that load and cannot establish an isolated before/after speedup. Each turn had a 45-second deadline; a two-turn conversation can take up to twice that. The quality cohort changes wording, so its score is separate from the same-corpus comparison.', '',
        'Compiler validation proves preservation of the interpreted goal; it cannot prove that the goal reflects user intent. A clear description is returned for review. The deterministic engine remains independent of the model.', '',
        'Timeout call counts are unknown; the exporter corrects the initial instrumentation default zero to null when no stage completed. No network/viewer-delivery performance claims are made by this agent evaluation.', '',
        '## Remaining failures', '']
    failures = []
    for label, report in [('Mixed-quality', baseline), ('Quality/conversation', quality)]:
        for row in report['agents']:
            if not row['ok']:
                failures.append(f"- {label} `{row['id']}`: {row.get('reason', 'unknown')} ({row.get('status', 'unmeasured')}).")
    lines += failures or ['None in these two runs.']
    if args.conversations:
        report = json.loads(args.conversations.read_text())
        (args.output / 'agents-conversations-final.json').write_text(json.dumps(report, indent=2) + '\n')
        rows = report['agents']
        count, median, p95 = summary(rows)
        lines += ['', '## Focused clarification recheck', '',
            f'After adding an unresolved-player-reference guard and strengthening carry-forward instructions: **{count}** exact conversations; median {median}s, p95 {p95}s. This 12-case rerun is separate from the original conversation result above; it does not overwrite the lost-constraint failure.', '',
            'The guard asks which player before calling the model when the first request has an unresolved possessive reference. It does not guess or rewrite metric constraints. Follow-up semantics remain model-interpreted, not guaranteed.', '',
            '[Focused conversation results](agents-conversations-final.json)']
        lines += [f"- `{row['id']}`: {row.get('reason')} ({row.get('status')})." for row in rows if not row['ok']]
    if args.serial:
        report = json.loads(args.serial.read_text())
        (args.output / 'agents-serial-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
        lines += ['', '## Serial timing smoke', '',
            'Three requests/conversations after the full suites finished, concurrency 1. This tiny sample is a latency observation, not an SLO or accuracy estimate.', '',
            '| Case | Result | Total seconds | Model calls |', '| --- | --- | ---: | ---: |']
        for row in report['agents']:
            lines.append(f"| {row['id']} | {'pass' if row['ok'] else 'fail'} | {row.get('seconds', 'unknown')} | {row.get('model_calls', 'unknown')} |")
        lines += ['', '[Serial raw results](agents-serial-smoke.json)']
    lines += ['', '[Original results](README.md) · [Updated mixed-quality raw results](agents-improved-baseline.json) · [Updated quality/conversation raw results](agents-improved-quality.json)', '']
    (args.output / 'agents-improved.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
