"""Model per role from the user backend: a set deployment swaps that role's agent live at the same
endpoint; an empty one or an unreachable backend keeps the environment's model."""
import asyncio

from narrative_engine.agents.llm import LLMAgents, LLMSettings, ModelSettings

BASE = ModelSettings("env-model", "https://example.invalid/openai/v1", "key", "low")
SETTINGS = LLMSettings(BASE, BASE, BASE, BASE)


class Roles:
    def __init__(self, engine=None, fail=False):
        self.engine, self.fail = engine or {}, fail

    async def get(self):
        if self.fail:
            raise OSError("unreachable")
        empty = {"deployment": "", "effort": ""}
        return {"value": {"engine": {r: self.engine.get(r, empty) for r in ("summary", "compression", "analyst",
                                                                           "author")}}}


def apply(roles, role="author"):
    agents = LLMAgents(SETTINGS, roles=roles)
    asyncio.run(agents._apply_roles(role))
    return agents.models[role]


def test_a_set_deployment_swaps_the_role_at_the_same_endpoint():
    model = apply(Roles({"author": {"deployment": "gpt-6-luna", "effort": ""}}))
    assert (model.model, model.effort, model.base_url) == ("gpt-6-luna", None, BASE.base_url)
    assert apply(Roles({"author": {"deployment": "gpt-6-luna", "effort": ""}}), "summary") == BASE


def test_an_empty_deployment_or_unreachable_backend_keeps_the_environment_model():
    assert apply(Roles()) == BASE
    assert apply(Roles(fail=True)) == BASE
    assert apply(None) == BASE
