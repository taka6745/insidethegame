"""Fast, opt-in checks for evaluator bookkeeping; no model calls or pytest collection."""
import asyncio
import unittest

from backend.agents.models import Clarification, Goal, PlanOutcome
from .balanced_cases import balanced_cases
from .conversation_eval import evaluate_conversation

GOAL = Goal(description="Count Mbappé headed contacts", player_ids=("mbappe",), body_part="head")
READY = PlanOutcome(status="ready", source="fixture", goal=GOAL, rule=GOAL.target_rule("match"), model_calls=0)
ASK = PlanOutcome(status="clarification", source="fixture", model_calls=0,
                  clarification=Clarification(question="Which player?", options=["Mbappé", "Palmer"]),
                  message="Which player?")


class ScriptedWorkflow:
    def __init__(self, responses):
        self.responses, self.requests = iter(responses), []

    async def plan(self, prompt, context, history):
        self.requests.append({"prompt": prompt, "context": context, "history": list(history)})
        return next(self.responses)


def run(responses, case=None, check=None):
    case = case or {"id": "check", "quality": "poor", "prompt": "His headers?", "must_clarify": True,
                   "replies": ["Mbappé.", "All his headed contacts."], "expected_status": ["ready"]}
    workflow = ScriptedWorkflow(responses)
    result = asyncio.run(evaluate_conversation(workflow, case, {"match_id": "match"},
                         check or (lambda case, rule: {"ok": True})))
    return result, workflow


class ConversationChecks(unittest.TestCase):
    def test_lucky_guess_is_not_a_pass(self):
        result, workflow = run([READY])
        self.assertFalse(result["ok"])
        self.assertTrue(result["unsafe_guess"])
        self.assertTrue(result["final_answer_correct"])
        self.assertFalse(result["first_turn_ready_correct"])
        self.assertEqual(len(workflow.requests), 1)

    def test_two_replies_preserve_questions_and_options(self):
        result, workflow = run([ASK, ASK, READY])
        self.assertTrue(result["ok"])
        self.assertTrue(result["first_turn_correct"])
        self.assertEqual(result["turn_count"], 3)
        self.assertEqual(result["unnecessary_clarifications"], 1)
        self.assertEqual([r["prompt"] for r in workflow.requests], ["His headers?", "Mbappé.", "All his headed contacts."])
        self.assertEqual(len(workflow.requests[-1]["history"]), 4)
        self.assertIn("Options:\n1. Mbappé\n2. Palmer", workflow.requests[-1]["history"][1]["content"])
        self.assertNotIn("expected", str(workflow.requests))

    def test_fully_specified_prompt_with_clarification_can_recover(self):
        case = {"id": "clear", "quality": "clear", "prompt": "Count Mbappé's headed contacts.",
                "replies": ["All Mbappé's headed contacts."], "must_clarify": False, "expected_status": ["ready"]}
        result, _ = run([ASK, READY], case)
        self.assertTrue(result["ok"])
        self.assertFalse(result["first_turn_correct"])
        self.assertEqual(result["unnecessary_clarifications"], 1)

    def test_ready_stops_without_feeding_replies(self):
        case = {"id": "clear", "quality": "clear", "prompt": "Headers", "replies": ["unused"],
                "expected_status": ["ready"]}
        result, workflow = run([READY], case)
        self.assertTrue(result["first_turn_ready_correct"])
        self.assertEqual(len(workflow.requests), 1)

    def test_wrong_value_counted_after_reply(self):
        result, _ = run([ASK, READY], check=lambda case, rule: {"ok": False, "reason": "wrong_event_value"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["wrong_ready_values"], 1)

    def test_timeout_is_failure_not_zero_calls(self):
        failed = PlanOutcome(status="failed", source="local", message="The calculation request timed out.")
        result, _ = run([failed])
        self.assertFalse(result["ok"])
        self.assertEqual(result["timeout_count"], 1)
        self.assertIsNone(result["model_calls"])

    def test_reply_budget_does_not_loop(self):
        result, workflow = run([ASK, ASK, ASK])
        self.assertFalse(result["ok"])
        self.assertEqual(len(workflow.requests), 3)

    def test_unsupported_control_is_separate_from_ready(self):
        case = {"id": "control", "quality": "control", "prompt": "Predict a goal", "replies": ["unused"], "expected_status": ["unsupported"]}
        result, workflow = run([PlanOutcome(status="unsupported", source="fixture", model_calls=0)], case)
        self.assertEqual(len(workflow.requests), 1)
        self.assertTrue(result["ok"])
        self.assertTrue(result["first_turn_correct"])
        self.assertFalse(result["first_turn_ready_correct"])

    def test_unsupported_control_cannot_pass_a_ready_rule(self):
        case = {"id": "control", "quality": "control", "prompt": "Predict a goal",
                "replies": ["unused"], "expected_status": ["unsupported"]}
        result, workflow = run([READY], case)
        self.assertFalse(result["ok"])
        self.assertEqual(result["unexpected_ready"], 1)
        self.assertEqual(len(workflow.requests), 1)

    def test_matched_cohort_has_balanced_bands_and_fixed_gold(self):
        cases = balanced_cases()
        self.assertEqual(len(cases), 100)
        for quality in ("clear", "average", "poor"):
            self.assertEqual(sum(row["quality"] == quality for row in cases), 30)
        for index in range(1, 31):
            group = [row for row in cases if row['intent_id'] == f'intent-{index:02}']
            self.assertEqual(len({str(row['expected_rule']) for row in group}), 1)
            self.assertEqual(len({str(row['expected_weights']) for row in group}), 1)
        self.assertTrue(all(len(row['replies']) == 2 for row in cases))


if __name__ == '__main__':
    unittest.main()
