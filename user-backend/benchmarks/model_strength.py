"""Opt-in pinned-model comparison using the existing SDK workflow and gold oracle."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import statistics
import subprocess

from backend.adapters.events import OptaInspiredAdapter
from backend.adapters.llm import LocalJsonModel
from backend.agents.compiler import StructuredRuleCompiler
from backend.agents.data_skill import EventDataSkill
from backend.agents.semantics import GOAL_INSTRUCTIONS, STRUCTURED_GOAL_INSTRUCTIONS
from backend.agents.measurement_support import MEASUREMENT_POLICY
from backend.agents.orchestrator import GoalAgent
from backend.agents.settings import AgentSettings
from backend.agents.workflow import RuleWorkflow
from .conversation_eval import evaluate_conversation
from .correctness import COHORTS, FIXTURE, evaluate_rule, gold_check
from .data_transfer_cases import remap_fixture
from .model_observer import ModelObserver, digest, pin_verification

BASELINE = Path(__file__).with_name('prompts') / 'goal-baseline.txt'
BASELINE_SCHEMA = BASELINE.with_suffix('.schema.json')
ROOT = Path(__file__).resolve().parents[2]


def load_models(path):
    """Inside the repository, model-routing configuration must be Git-ignored."""
    path = path.resolve()
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        relative = None
    if relative is not None and (ROOT / ".git").exists() and subprocess.run(['git', 'check-ignore', '-q', str(relative)], cwd=ROOT).returncode:
        raise ValueError('Model configuration inside the repository must be in an ignored file')
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or set(raw) != {'models'} or not isinstance(raw['models'], list) or not raw['models']:
        raise ValueError('Expected a nonempty models list')
    labels = set()
    for item in raw['models']:
        if not isinstance(item, dict) or set(item) != {'label', 'model', 'expected_models'}:
            raise ValueError('Each model needs label, model and expected_models')
        label = item['label']
        if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', label) or label in labels:
            raise ValueError('Model labels must be unique short identifiers')
        labels.add(label)
        values = [item['model']]
        expected = item['expected_models']
        if not isinstance(expected, list) or not expected:
            raise ValueError('Each model needs a nonempty returned-model allowlist')
        values += expected
        if any(not isinstance(value, str) or not 1 <= len(value) <= 200 or '://' in value for value in values):
            raise ValueError('Model IDs must be names, not endpoints')
    return raw['models']


def variant_order(case_index, variants=('baseline', 'current')):
    ordered = ('baseline', 'current', 'schema', 'skill', 'schema_skill', 'skill_added', 'schema_skill_added')
    if case_index % 2:
        ordered = ordered[::-1]
    return tuple(variant for variant in ordered if variant in variants)


def build_workflow(model_config, variant, case_timeout, observer, candidate_instructions=None):
    url = os.getenv('LOCAL_LLM_BASE_URL')
    if not url:
        raise ValueError('Configure LOCAL_LLM_BASE_URL in the ignored environment file')
    model = LocalJsonModel(url, model_config['model'], os.getenv('LOCAL_LLM_API_KEY', ''),
                          min(case_timeout, float(os.getenv('LOCAL_LLM_TIMEOUT_SECONDS', '120'))),
                          transport=observer, name='model_comparison_goal')
    if variant == 'baseline':
        agent = GoalAgent(model, instructions=BASELINE.read_text(), compact_contract=False)
        agent.schema = json.loads(BASELINE_SCHEMA.read_text())
    elif variant == 'schema':
        agent = GoalAgent(model, response_mode='schema')
    elif variant in {'skill', 'schema_skill', 'skill_added', 'schema_skill_added'}:
        structured = variant.startswith('schema')
        # "Added" keeps the default prompt byte-identical, so only the data skill differs.
        instructions = (MEASUREMENT_POLICY + (STRUCTURED_GOAL_INSTRUCTIONS if structured else GOAL_INSTRUCTIONS)
                        if variant.endswith('_added') else None)
        agent = GoalAgent(model, response_mode='schema' if structured else 'prompt', instructions=instructions,
                          data_skill=EventDataSkill(OptaInspiredAdapter().data_reference()))
    elif candidate_instructions is not None:
        agent = GoalAgent(model, instructions=candidate_instructions, compact_contract=True)
    else:
        agent = GoalAgent(model)
    metadata = {'prompt_sha256': digest(agent.instructions), 'schema_sha256': digest(agent.schema)}
    if variant in {'skill', 'schema_skill', 'skill_added', 'schema_skill_added'}:
        metadata['data_skill_sha256'] = agent.data_skill.fingerprint
    return RuleWorkflow(agent, StructuredRuleCompiler(), source='local', timeout_seconds=case_timeout,
                        max_repairs=AgentSettings.from_env().max_repairs), metadata


async def compare(args, models, selected, scenario, events, output):
    rows, active_observers = [], {}
    variants = getattr(args, 'variants', ('baseline', 'current'))
    candidate_path = getattr(args, 'candidate_prompt', None)
    candidate_instructions = candidate_path.read_text() if candidate_path else None
    context = {key: scenario[key] for key in ('match_id', 'players', 'teams')}
    context['standard_stats'] = []
    semaphore = asyncio.Semaphore(args.concurrency)

    async def paired_case(model_config, case, index):
        async with semaphore:
            for variant in variant_order(index, variants):
                observer = ModelObserver()
                key = (model_config['label'], variant, case['id'])
                active_observers[key] = observer
                metadata = {}
                try:
                    workflow, metadata = build_workflow(model_config, variant, args.case_timeout, observer, candidate_instructions)
                    result = await evaluate_conversation(workflow, case, context,
                        lambda case, rule: evaluate_rule(case, rule, events, scenario['events']))
                except Exception as exc:
                    result = {'id': case['id'], 'quality': case['quality'], 'ok': False,
                              'reason': type(exc).__name__}
                pin = pin_verification(observer.calls, model_config['expected_models'])
                interpretation_ok = result['ok']
                row = {**result, 'model_label': model_config['label'], 'requested_model': model_config['model'],
                       'variant': variant, 'interpretation_ok': interpretation_ok,
                       'ok': interpretation_ok and pin['pin_verified'], **metadata, **pin,
                       'calls': observer.calls}
                rows.append(row)
                output.write(json.dumps(row) + '\n')
                output.flush()
                active_observers.pop(key, None)
                print(f"{model_config['label']} / {variant} / {case['id']}: "
                      f"{'PASS' if row['ok'] else 'FAIL'} [{pin['pin_reason']}]", flush=True)

    async def sequential_models():
        for config in models:
            tasks = [asyncio.create_task(paired_case(config, case, index)) for index, case in enumerate(selected)]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    try:
        async with asyncio.timeout(args.suite_timeout):
            await sequential_models()
    except TimeoutError:
        pass
    complete = {(row['model_label'], row['variant'], row['id']) for row in rows}
    for config in models:
        for case in selected:
            for variant in variants:
                key = (config['label'], variant, case['id'])
                if key not in complete:
                    observer = active_observers.get(key)
                    calls = observer.calls if observer else []
                    row = {'model_label': config['label'], 'requested_model': config['model'],
                           'variant': variant, 'id': case['id'], 'quality': case['quality'],
                           'ok': False, 'interpretation_ok': False, 'reason': 'suite_timeout_unmeasured',
                           **pin_verification(calls, config['expected_models']), 'calls': calls}
                    rows.append(row)
                    output.write(json.dumps(row) + '\n')
    return rows


def write_summary(report, path):
    lines = ['# Pinned-model comparison', '',
             'Actual model identity is the name reported by the response, not independent proof of which weights ran. Missing identity or an unexpected substitute never counts as a pinned pass.', '',
             '| Model label | Variant | Pinned passes | Interpretation passes | Unverified rows | Median total seconds | Reported models |',
             '| --- | --- | ---: | ---: | ---: | ---: | --- |']
    rows = report['results']
    for model in report['models']:
        for variant in report.get('variants', ('baseline', 'current')):
            group = [r for r in rows if r['model_label'] == model['label'] and r['variant'] == variant]
            timings = [r['seconds'] for r in group if 'seconds' in r]
            timing = f'{statistics.median(timings):.2f}' if timings else 'unmeasured'
            actual = sorted({name for r in group for name in r.get('actual_models', [])})
            lines.append(f"| {model['label']} | {variant} | {sum(r['ok'] for r in group)}/{len(group)} | "
                         f"{sum(r['interpretation_ok'] for r in group)}/{len(group)} | "
                         f"{sum(not r['pin_verified'] for r in group)} | {timing} | {', '.join(actual) or 'none'} |")
    lines += ['', 'When both variants are selected, they are paired within each case with their order alternating by case. Models run sequentially; cases use the configured concurrency. This reduces but does not remove time/load effects. Cache-Control requests no-cache; the server may ignore it. The comparison changes prompt instructions and schema presentation together, so it does not isolate either one.', '',
              'The same Microsoft Agent Framework workflow, compiler, repair limit and oracle are used. No gold results enter the model request. Deterministic-only responses are recorded as model-not-invoked, not pinned model successes. Failed HTTP calls, cancellations and token usage remain in report.json; no raw response bodies, endpoints or credentials are saved.', '',
              '[Full results](report.json)', '']
    path.write_text('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models-config', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--cohort', choices=['balanced', 'baseline', 'transfer', 'data-transfer'], default='balanced')
    parser.add_argument('--case-id', action='append')
    parser.add_argument('--variants', nargs='+', choices=['baseline', 'current', 'schema', 'skill', 'schema_skill',
                                                        'skill_added', 'schema_skill_added'], default=['baseline', 'current'])
    parser.add_argument('--candidate-prompt', type=Path, help='Override current instructions; retain compact schema')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--concurrency', type=int, choices=range(1, 9), default=2)
    parser.add_argument('--case-timeout', type=float, default=60)
    parser.add_argument('--suite-timeout', type=float, default=1200)
    parser.add_argument('--output', type=Path, default=Path('.local/benchmarks/model-strength'))
    args = parser.parse_args()
    if args.case_timeout <= 0 or args.suite_timeout <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error('Timeouts and limits must be positive')
    if len(set(args.variants)) != len(args.variants):
        parser.error('Each variant may be selected only once')
    if args.candidate_prompt and 'current' not in args.variants:
        parser.error('--candidate-prompt requires the current variant')
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    logging.basicConfig(level=logging.ERROR)
    models = load_models(args.models_config)
    selected = [case for case in COHORTS[args.cohort]() if not args.case_id or case['id'] in args.case_id]
    if args.case_id and set(args.case_id) - {case['id'] for case in selected}:
        parser.error('Unknown case ID for this cohort')
    if args.limit:
        selected = selected[:args.limit]
    scenario = json.loads(FIXTURE.read_text())
    if args.cohort == 'data-transfer':
        scenario = remap_fixture(scenario)
    events = [OptaInspiredAdapter().adapt(raw) for raw in scenario['events']]
    gold = gold_check(scenario, events, selected)
    if any(not row['ok'] for row in gold):
        raise ValueError('Independent gold checks failed; do not run a model comparison')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'cohort': args.cohort,
              'models': models, 'variants': args.variants, 'case_ids': [case['id'] for case in selected],
              'cases_sha256': digest(selected), 'fixture_sha256': digest(scenario),
              'concurrency': args.concurrency, 'case_timeout_seconds': args.case_timeout,
              'suite_timeout_seconds': args.suite_timeout, 'max_repairs': AgentSettings.from_env().max_repairs,
              'gold': gold}
    with (args.output / 'results.jsonl').open('w') as output:
        report['results'] = asyncio.run(compare(args, models, selected, scenario, events, output))
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    write_summary(report, args.output / 'README.md')
    print(f"Pinned passes: {sum(row['ok'] for row in report['results'])}/{len(report['results'])}")
    raise SystemExit(0 if all(row['ok'] for row in report['results']) else 1)


if __name__ == '__main__':
    main()
