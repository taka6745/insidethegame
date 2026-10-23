"""Publish the frozen balanced evaluation and its inspectable user dialogue scripts."""
import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from benchmarks.balanced_cases import balanced_cases


def percent(rows, key):
    return f"{sum(bool(row.get(key)) for row in rows)}/{len(rows)}"


def median(values):
    return f"{statistics.median(values):.2f}" if values else "—"


def p95(values):
    values = sorted(values)
    return f"{values[min(len(values) - 1, math.ceil(len(values) * .95) - 1)]:.2f}" if values else "—"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('.local/benchmarks/balanced'))
    args = parser.parse_args()
    report = json.loads(args.input.read_text())
    cases = balanced_cases()
    expected_hash = hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()
    if report.get('selected_cases_sha256') != expected_hash:
        raise ValueError('The frozen evaluation cases differ from this checkout; do not relabel the run')
    by_id = {case['id']: case for case in cases}
    rows = report['agents']
    if len(rows) != 100 or {row['id'] for row in rows} != set(by_id):
        raise ValueError('Expected exactly the frozen 100 cases, including explicitly unmeasured ones')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'agents-balanced.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.output / 'agents-balanced-cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    groups = {quality: [row for row in rows if by_id[row['id']]['quality'] == quality]
              for quality in ('clear', 'average', 'poor', 'control')}
    stats = [row for row in rows if by_id[row['id']]['quality'] != 'control']
    poor_required = [row for row in groups['poor'] if by_id[row['id']]['must_clarify']]
    lines = ['# Balanced prompt-quality evaluation', '', 'Measured 18 October 2026.', '',
        '**30 distinct stat intents × 3 wordings = 90 stat requests, plus 10 unsupported controls.** Each intent has the same independent event/revision gold answer across its clear, average and poor wording. Runtime semantics had already been developed against this original intent family: this is a wording/clarification stress cohort, not a fully held-out new-intent generalisation test. This controls calculation complexity when comparing prompt quality; these are not 90 independent football scenarios. The oracle uses the existing synthetic Opta-inspired fixture: 35 event deliveries, including corrections and deletions. Each ready rule is checked at every delivery, on historical backfill, and for exact filter constraints.', '',
        f'**Final correct stat requests: {percent(stats, "ok")}. Unsupported controls: {percent(groups["control"], "ok")}.**', '',
        '| Wording | Correct first decision | Correct stat on first turn | Correct after feedback | Median total seconds |',
        '| --- | ---: | ---: | ---: | ---: |']
    for quality in ('clear', 'average', 'poor'):
        group = groups[quality]
        lines.append(f'| {quality.title()} | {percent(group, "first_turn_correct")} | {percent(group, "first_turn_ready_correct")} | {percent(group, "ok")} | {median([r["seconds"] for r in group if "seconds" in r])} |')
    lines += ['', '“Correct first decision” counts asking a necessary clarification as correct. “Correct stat on first turn” requires an immediately correct rule and disallows guessing missing information. Final correctness requires the correct rule **and** any required initial clarification; a lucky guess does not pass.', '',
        '## Feedback and failures', '',
        '| Wording | Cases needing clarification | Questions asked | Unnecessary questions | Missed required clarification | Wrong ready values | Wrong constraints | Timeouts |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for quality in ('clear', 'average', 'poor', 'control'):
        group = groups[quality]
        required = sum(by_id[row['id']]['must_clarify'] for row in group)
        totals = [sum(row.get(key, 0) for row in group) for key in
                  ('clarification_count', 'unnecessary_clarifications', 'missed_clarification',
                   'wrong_ready_values', 'wrong_ready_constraints', 'timeout_count')]
        lines.append(f'| {quality.title()} | {required} | ' + ' | '.join(str(value) for value in totals) + ' |')
    lines += ['', f'{len(poor_required)} poor prompts deliberately omit an entity, metric or time detail. The remaining poor prompts use typos/shorthand while retaining the intended information. A prepared complete natural-language restatement supplies the intended request **only after the agent asks**. A second complete restatement is available if it asks again; then the case stops. This tests recovery with informative user feedback, not the harder case of terse slot-only replies (covered separately in the earlier conversation cohort). Clarification-question relevance is not independently graded here. No answer includes expected numeric results or filter DSL.', '',
        f'Unsupported controls were correctly rejected initially in {percent(groups["control"], "first_turn_correct")} cases and finally in {percent(groups["control"], "ok")}. Falsely accepted controls: {sum(row.get("unexpected_ready", 0) for row in groups["control"])}. Their replies preserve the unsupported request rather than changing it to an easier supported metric.', '',
        'Failures and question counts overlap; they are diagnostic measures, not mutually exclusive categories. A failed request before answering a required question is recorded as a missed clarification, but only a ready/reuse response is an unsafe guess.', '',
        '## Latency and method', '',
        f'The frozen run used concurrency **{report["concurrency"]}**, a **{report["case_timeout_seconds"]:g}s** deadline per turn and **{report["suite_timeout_seconds"]:g}s** for the suite. No semantic tuning or prompt rewrites were made during this run. Each case starts a fresh request; it can use up to two scripted replies (three turns total). Model context contains only the match/team/player catalogue and an empty standard-stat catalogue, isolating custom-filter interpretation rather than ETL stat reuse. Replies preserve the complete user history and the same numbered assistant options as the application.', '',
        '| Wording | Median first turn seconds | p95 first turn seconds | p95 total seconds | Mean turns |',
        '| --- | ---: | ---: | ---: | ---: |']
    for quality, group in groups.items():
        first = [row['turns'][0]['seconds'] for row in group if row.get('turns')]
        total = [row['seconds'] for row in group if 'seconds' in row]
        turns = [row['turn_count'] for row in group if 'turn_count' in row]
        lines.append(f'| {quality.title()} | {median(first)} | {p95(first)} | {p95(total)} | {f"{statistics.mean(turns):.2f}" if turns else "—"} |')
    unmeasured = sum(row.get('reason') == 'suite_timeout_unmeasured' for row in rows)
    lines += ['', f'Suite-timeout/unmeasured cases: **{unmeasured}**. Latency excludes human thinking time; scripted replies arrive immediately. p95 uses the nearest-rank method. Model-call counts are null when a timeout leaves them unknown. Typed compilation is verified, while semantic understanding is evaluated rather than guaranteed. This single local-model run is not a production accuracy or capacity claim.', '',
        '## Cases that did not pass', '',
        '| Case / request | First → final status | Result |', '| --- | --- | --- |']
    failures = [row for row in rows if not row['ok']]
    for row in failures:
        first = row.get('turns', [{}])[0].get('status', 'unmeasured')
        lines.append(f'| {row["id"]}: {by_id[row["id"]]["prompt"]} | {first} → {row.get("status", "unmeasured")} | {row.get("reason", "unknown")} |')
        if row.get('goal'):
            lines.append(f'| Model interpretation | {row["goal"]["description"]} | Clarification was required |')
    if not failures:
        lines.append('| — | — | All cases passed in this run |')
    lines += ['', '[Exact prompts, prepared replies and gold cases](agents-balanced-cases.json) · [All per-turn results](agents-balanced.json) · [Earlier agent comparison](agents-improved.md)', '']
    (args.output / 'agents-balanced.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
