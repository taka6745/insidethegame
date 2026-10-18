import pytest

from backend.coding import Case, Goal, build_calculation

GOAL = Goal("Count headed shots since minute 20", frozenset({"type", "bodyPart", "minute"}), (
    Case("exclude foot shots and earlier headers", ({"type": "shot", "bodyPart": "head", "minute": 19},
                                                  {"type": "shot", "bodyPart": "foot", "minute": 21}), 0),
    Case("include minute 20 boundary, exclude headed passes", ({"type": "shot", "bodyPart": "head", "minute": 20},
                                                             {"type": "pass", "bodyPart": "head", "minute": 21}), 1),
))


class ScriptedAgent:
    def __init__(self):
        self.calls = []

    def generate(self, goal, previous_source, feedback):
        self.calls.append((goal, previous_source, feedback))
        return f"candidate-{len(self.calls)}"


class ScriptedExecutor:
    """Test double only: no generated source is executed or claimed to work."""
    def __init__(self, results):
        self.results = iter(results)

    def evaluate(self, source, cases):
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def test_semantically_wrong_result_is_repaired_not_accepted():
    agent = ScriptedAgent()
    result = build_calculation(GOAL, GOAL.required_fields, agent, ScriptedExecutor([[2, 2], [0, 1]]))
    assert result.source == "candidate-2" and result.attempts == 2
    assert "exclude foot shots" in agent.calls[1][2]
    assert agent.calls[1][1] == "candidate-1"


def test_stops_after_three_repairs():
    agent = ScriptedAgent()
    result = build_calculation(GOAL, GOAL.required_fields, agent, ScriptedExecutor([[9, 9]] * 4))
    assert result.source is None and result.attempts == 4 and len(agent.calls) == 4


def test_missing_data_never_generates_code():
    agent = ScriptedAgent()
    result = build_calculation(GOAL, {"minute"}, agent, ScriptedExecutor([]))
    assert result.attempts == 0 and not agent.calls


@pytest.mark.parametrize("bad", [[False, True], [float("nan"), 1], [0], RuntimeError("executor timeout")])
def test_invalid_or_failed_execution_requires_repair(bad):
    result = build_calculation(GOAL, GOAL.required_fields, ScriptedAgent(), ScriptedExecutor([bad, [0, 1]]))
    assert result.attempts == 2 and result.error is None
