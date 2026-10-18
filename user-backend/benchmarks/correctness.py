"""Opt-in gold/oracle and real-agent checks, never collected by pytest."""
import argparse
import asyncio
import hashlib
import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path

from backend.adapters.events import OptaInspiredAdapter
from backend.agents.workflow import workflow_from_env
from backend.models.rules import Rule
from backend.services.filter_engine import FilterEngine
from .cases import cases

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/filter-lab.json"


def expected_trace(case, raw_events):
    """Revision ledger using hand-written per-revision weights, not rule logic."""
    seen, current, trace = {}, {}, []
    for event in raw_events:
        key, revision = event["eventId"], event["revision"]
        if revision > seen.get(key, 0):
            seen[key] = revision
            current[key] = Decimal(str(case["expected_weights"].get(f"{key}@{revision}", 0)))
        trace.append(float(sum(current.values(), Decimal(0))))
    return trace


def evaluate_rule(case, candidate, events, raw_events):
    expected = expected_trace(case, raw_events)
    engine = FilterEngine()
    calc = engine.register(candidate)
    for index, event in enumerate(events):
        engine.ingest(event)
        actual = engine.get(calc.calculation_id).value
        if actual != expected[index]:
            return {"ok": False, "reason": "wrong_event_value", "delivery": index + 1,
                    "expected": expected[index], "actual": actual}
    # Late registration must also reconstruct the same result.
    backfill = FilterEngine().register(candidate, events).value
    if backfill != expected[-1]:
        return {"ok": False, "reason": "wrong_backfill", "expected": expected[-1], "actual": backfill}
    # A matching fixture alone is insufficient: disallow changed constraints that
    # happen to produce the same answer on this match. eq/singleton-in normalize.
    if candidate.calculation_id != Rule.model_validate(case["expected_rule"]).calculation_id:
        return {"ok": False, "reason": "different_constraints", "actual_rule": candidate.model_dump(mode="json")}
    return {"ok": True, "final_value": expected[-1], "deliveries_checked": len(events)}


def gold_check(scenario, events):
    rows = []
    for case in cases():
        if "expected_rule" not in case:
            continue
        checked = evaluate_rule(case, Rule.model_validate(case["expected_rule"]), events, scenario["events"])
        rows.append({"id": case["id"], **checked})
    return rows


async def agent_check(args, scenario, events, output):
    semaphore = asyncio.Semaphore(args.concurrency)
    selected = [c for c in cases() if not args.case_id or c["id"] in args.case_id]
    if args.limit:
        selected = selected[:args.limit]
    rows = []
    workflow = workflow_from_env()
    if workflow.source != "local":
        raise ValueError("Agent evaluation requires LOCAL_LLM_MODE=local; fixture answers are not an evaluation")
    workflow.timeout_seconds = args.case_timeout
    context = {key: scenario[key] for key in ("match_id", "teams", "players")}
    context["standard_stats"] = []

    async def run(case):
        async with semaphore:
            start = time.perf_counter()
            try:
                outcome = await workflow.plan(case["prompt"], context)
                checked = {"ok": outcome.status in case["expected_status"], "reason": "status",
                           "expected_status": case["expected_status"], "actual_status": outcome.status}
                if checked["ok"] and outcome.status == "ready":
                    checked = evaluate_rule(case, outcome.rule, events, scenario["events"])
                row = {"id": case["id"], "quality": case["quality"], "attempts": outcome.attempts,
                       "status": outcome.status, "seconds": round(time.perf_counter() - start, 3),
                       "actual_rule": outcome.rule.model_dump(mode="json") if outcome.rule else None, **checked}
            except Exception as exc:
                # Never save provider exception bodies, endpoint URLs or credentials.
                row = {"id": case["id"], "ok": False, "reason": type(exc).__name__}
            rows.append(row)
            output.write(json.dumps(row) + "\n")
            output.flush()
            print(f"{case['id']}: {'PASS' if row['ok'] else 'FAIL'} {row.get('reason', '')}", flush=True)

    tasks = [asyncio.create_task(run(case)) for case in selected]
    _, pending = await asyncio.wait(tasks, timeout=args.suite_timeout)
    for task in pending:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    complete = {row["id"] for row in rows}
    for case in selected:
        if case["id"] not in complete:
            row = {"id": case["id"], "ok": False, "reason": "suite_timeout_unmeasured"}
            rows.append(row)
            output.write(json.dumps(row) + "\n")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", action="store_true", help="Explicit opt-in: calls the configured local model")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".local/benchmarks/correctness"))
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--case-timeout", type=float, default=60)
    parser.add_argument("--suite-timeout", type=float, default=900)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-id", action="append")
    args = parser.parse_args()
    if args.case_timeout <= 0 or args.suite_timeout <= 0:
        parser.error("Timeouts must be positive")
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    logging.basicConfig(level=logging.ERROR)
    scenario = json.loads(FIXTURE.read_text())
    events = [OptaInspiredAdapter().adapt(row) for row in scenario["events"]]
    gold = gold_check(scenario, events)
    args.output.mkdir(parents=True, exist_ok=True)
    failures = [row for row in gold if not row["ok"]]
    report = {"fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), "gold": gold,
              "agent_calls": False, "max_repairs": int(os.getenv("AGENT_MAX_REPAIRS", "3")),
              "cases_sha256": hashlib.sha256(Path(__file__).with_name("cases.py").read_bytes()).hexdigest()}
    if failures:
        print(json.dumps(failures, indent=2))
    elif args.agents:
        with (args.output / "agent-results.jsonl").open("w") as output:
            report["agents"] = asyncio.run(agent_check(args, scenario, events, output))
        report.update(agent_calls=True, case_timeout_seconds=args.case_timeout, suite_timeout_seconds=args.suite_timeout,
                      concurrency=args.concurrency)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Gold: {len(gold) - len(failures)}/{len(gold)} passed")
    if "agents" in report:
        print(f"Agents: {sum(row['ok'] for row in report['agents'])}/{len(report['agents'])} passed")
    raise SystemExit(1 if failures or any(not r["ok"] for r in report.get("agents", [])) else 0)


if __name__ == "__main__":
    main()
