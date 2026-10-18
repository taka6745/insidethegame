"""Bounded scripted user feedback for standalone evaluations, not runtime planning."""
import time


from backend.agents.conversation import assistant_message


def check_outcome(case, outcome, evaluate):
    if outcome.status not in case["expected_status"]:
        return {"ok": False, "reason": "status", "expected_status": case["expected_status"],
                "actual_status": outcome.status}
    return evaluate(case, outcome.rule) if outcome.status == "ready" else {"ok": True, "reason": "status"}


async def evaluate_conversation(workflow, case, context, evaluate):
    start = time.perf_counter()
    history, turns = [], []
    replies = case.get("replies", [case["reply"]] if "reply" in case else [])
    if len(replies) > 2:
        raise ValueError("At most two scripted user replies are supported")
    prompt = case["prompt"]
    must_clarify = case.get("must_clarify", case.get("expected_initial_status") == ["clarification"])
    for turn_index in range(len(replies) + 1):
        turn_start = time.perf_counter()
        outcome = await workflow.plan(prompt, context, history=history)
        checked = check_outcome(case, outcome, evaluate)
        turns.append({"prompt": prompt, "status": outcome.status,
            "seconds": round(time.perf_counter() - turn_start, 3),
            "model_calls": outcome.model_calls, "stage_seconds": outcome.stage_seconds,
            "goal_failure_reasons": outcome.goal_failure_reasons,
            "question": outcome.message if outcome.status == "clarification" else None,
            "clarification": outcome.clarification.model_dump(mode="json") if outcome.clarification else None,
            "goal": outcome.goal.model_dump(mode="json") if outcome.goal else None,
            "actual_rule": outcome.rule.model_dump(mode="json") if outcome.rule else None,
            "timed_out": outcome.status == "failed" and "timed out" in outcome.message.lower(),
            "check": checked})
        if outcome.status != "clarification" or turn_index == len(replies):
            break
        history += [{"role": "user", "content": prompt},
                    {"role": "assistant", "content": assistant_message(outcome.model_dump(mode="json"))}]
        prompt = replies[turn_index]
    first = turns[0]
    required_satisfied = not must_clarify or first["status"] == "clarification"
    first_correct = first["status"] == "clarification" if must_clarify else first["check"]["ok"]
    clarification_count = sum(turn["status"] == "clarification" for turn in turns)
    final_checked = checked if required_satisfied else {"ok": False, "reason": "missed_clarification", "final_check": checked}
    return {"id": case["id"], "intent_id": case.get("intent_id"), "quality": case["quality"],
        "must_clarify": must_clarify, "attempts": outcome.attempts,
        "status": outcome.status, "seconds": round(time.perf_counter() - start, 3),
        "turn_count": len(turns), "turns": turns,
        "model_calls": (sum(turn["model_calls"] for turn in turns)
                        if all(turn["model_calls"] is not None for turn in turns) else None),
        "first_turn_correct": first_correct,
        "first_turn_ready_correct": not must_clarify and first["status"] == "ready" and first["check"]["ok"],
        "final_answer_correct": checked["ok"],
        "required_clarification_satisfied": required_satisfied,
        "missed_clarification": must_clarify and first["status"] != "clarification",
        "unsafe_guess": must_clarify and first["status"] in {"ready", "reuse"},
        "clarification_count": clarification_count,
        "unnecessary_clarifications": max(0, clarification_count - (1 if must_clarify else 0)),
        "wrong_ready_values": sum(turn["status"] == "ready" and turn["check"].get("reason") in
                                  {"wrong_event_value", "wrong_backfill"} for turn in turns),
        "wrong_ready_constraints": sum(turn["status"] == "ready" and turn["check"].get("reason") ==
                                       "different_constraints" for turn in turns),
        "unexpected_ready": sum(turn["status"] == "ready" and "ready" not in case["expected_status"] for turn in turns),
        "timeout_count": sum(turn["timed_out"] for turn in turns),
        "goal": outcome.goal.model_dump(mode="json") if outcome.goal else None,
        "actual_rule": outcome.rule.model_dump(mode="json") if outcome.rule else None, **final_checked}
