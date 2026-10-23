"""Audience targets and prompts read from the user backend (mocked HTTP), with ETag caching."""
import asyncio

import httpx

import pytest

from narrative_engine.agents.prompt_source import ROLES, HttpPromptSource, PromptUnavailable, shipped
from narrative_engine.audience.targets import HttpTargetSource, framing
from doubles.targets import default_targets
from narrative_engine.context.render import MatchInfo, Team
from support import BASE, Backend, client

def prompts_doc(revision, author):
    return {"revision": revision, "prompts": [
        {"role": "minute-summary", "version": 1, "template": shipped("minute-summary").template, "placeholders": []},
        {"role": "narrative-author", "version": revision, "template": author, "placeholders": []}]}


def test_targets_revalidate_with_the_etag_and_keep_the_last_copy_when_down():
    targets = [t for t in default_targets() if t["bucket_id"] == "home:simple"]
    backend = Backend({"/matches/demo/audience-config": {"revision": 3, "generation_targets": targets}})
    source = HttpTargetSource(BASE, client(backend), max_age=0)

    async def go():
        first = await source.current("demo")
        second = await source.current("demo")
        backend.down = True
        third = await source.current("demo")
        return first, second, third
    first, second, third = asyncio.run(go())
    assert first.revision == second.revision == third.revision == 3 and list(first.by_bucket) == ["home:simple"]
    assert backend.requests[:2] == [("/matches/demo/audience-config", None), ("/matches/demo/audience-config", '"3"')]


def test_framing_uses_layer_and_option_descriptions_and_team_names():
    info = MatchInfo("demo-1a2b3c4d", Team("t1", "Riverton Rovers", "RVR", "home"), Team("t2", "Forgeham United", "FGU", "away"),
                     True)
    target = {"bucket_id": "away:analytical", "selections": {"team": "away", "fan_style": "analytical"}, "layers": [
        {"id": "team", "description": "Which side the viewer supports.",
         "option": {"id": "away", "description": "Supports the away team.", "label": "{away}"}},
        {"id": "fan_style", "description": "How to explain.", "option": {"id": "analytical", "description": "Evidence."}}]}
    assert framing(target, info) == ("Audience bucket away:analytical:\n- Which side the viewer supports. Supports the "
                                     "away team.\n- How to explain. Evidence.\nHome team: Riverton Rovers. Away team: "
                                     "Forgeham United.\nThis audience supports Forgeham United.")


INFO = MatchInfo("m-1", Team("t1", "Riverton Rovers", "RVR", "home"), Team("t2", "Forgeham United", "FGU", "away"), True)


def one_layer(layer_id, option):
    return {"bucket_id": "b", "selections": {layer_id: option["id"]},
            "layers": [{"id": layer_id, "description": "Layer.", "option": {"description": "Option.", **option}}]}


@pytest.mark.parametrize("target, supports", [
    # Any layer id; an explicit team reference wins over the label.
    (one_layer("side", {"id": "blues", "team": "home", "label": "Blues"}), "Riverton Rovers"),
    (one_layer("allegiance", {"id": "red", "label": "{away} faithful"}), "Forgeham United"),
    # Neutral, both teams, or a layer that merely has id `team` with option `home` but no reference: no support line.
    (one_layer("side", {"id": "neutral", "label": "Neutral"}), None),
    (one_layer("side", {"id": "both", "label": "{home} v {away}"}), None),
    (one_layer("team", {"id": "home", "label": "Locals"}), None),
])
def test_framing_support_line_is_data_driven(target, supports):
    text = framing(target, INFO)
    assert text.endswith(f"This audience supports {supports}.") if supports else "supports" not in text.split("\n")[-1]


def test_default_targets_frame_like_the_backend_default_template():
    by_id = {t["bucket_id"]: t for t in default_targets()}
    assert framing(by_id["home:simple"], INFO).endswith("This audience supports Riverton Rovers.")
    assert "This audience supports" not in framing(by_id["neutral:simple"], INFO)


def test_prompts_come_from_the_api_validated_with_no_fallback_to_the_shipped_files():
    author = shipped("narrative-author").template
    backend = Backend({"/narrative-prompts": prompts_doc(2, author.replace("one to three", "one or two"))})
    source = HttpPromptSource(BASE, client(backend), max_age=0)

    async def go():
        edited = await source.current("narrative-author")
        with pytest.raises(PromptUnavailable, match="context-compression"):  # role missing from the API
            await source.current("context-compression")
        backend.documents["/narrative-prompts"] = prompts_doc(3, "Only {user_type} and {unknown}")
        with pytest.raises(PromptUnavailable, match="placeholders"):
            await source.current("narrative-author")
        backend.down = True
        pinned = await source.pinned("narrative-author", edited.label)
        return edited, pinned
    edited, pinned = asyncio.run(go())
    assert edited.label == "narrative-author@2" and "one or two" in edited.template
    assert pinned == edited  # a retried step keeps the prompt it started with


def test_prompts_and_targets_are_unavailable_without_the_backend():
    backend = Backend({})
    backend.down = True

    async def go():
        prompts = HttpPromptSource(BASE, client(backend))
        with pytest.raises(PromptUnavailable):
            await prompts.current("minute-summary")
        with pytest.raises(httpx.HTTPError):
            await HttpTargetSource(BASE, client(backend)).current("riverton-forgeham-1a2b3c4d")
        return await prompts.problems()
    assert asyncio.run(go()) == ["prompt minute-summary unavailable from the user backend (HTTPStatusError)"]


def test_prompt_problems_report_a_backend_that_stopped_answering():
    complete = {"revision": 1, "prompts": [{"role": r, "version": 1, "template": shipped(r).template}
                                           for r in ROLES]}
    backend = Backend({"/narrative-prompts": complete})
    source = HttpPromptSource(BASE, client(backend), max_age=0)

    async def go():
        healthy = await source.problems()
        backend.down = True
        return healthy, await source.problems()
    assert asyncio.run(go()) == ([], ["user backend unreachable (using its last answer)"])


def test_the_storyline_policy_comes_from_the_api_with_no_fallback():
    import json
    from narrative_engine.analysis.policy import SHIPPED, HttpPolicySource, PolicyUnavailable
    value = json.loads(SHIPPED.read_text())
    value["storylines"]["max_active"] = 2
    backend = Backend({"/storyline-policy": {"table": "storyline-policy", "revision": 7, "value": value}})
    source = HttpPolicySource(BASE, client(backend), max_age=0)

    async def go():
        policy = await source.current()
        backend.documents["/storyline-policy"] = {"table": "storyline-policy", "revision": 8,
                                                  "value": {k: v for k, v in value.items() if k != "repair"}}
        with pytest.raises(PolicyUnavailable, match="KeyError"):
            await source.current()
        return policy, await source.problems()
    policy, problems = asyncio.run(go())
    assert (policy.revision, policy.storylines["max_active"]) == (7, 2)
    assert problems == ["storyline policy unavailable from the user backend (KeyError)"]


def test_the_runtime_has_no_built_in_buckets():
    from doubles.fake_agents import FakeAgents
    from narrative_engine.core.orchestrator import MatchOrchestrator
    from narrative_engine.service import Router
    from narrative_engine.store.memory import MemoryStore
    import narrative_engine.audience.targets as runtime
    assert not hasattr(runtime, "default_targets") and not hasattr(runtime, "StaticTargets")
    store = MemoryStore()
    with pytest.raises(ValueError):
        Router(None, FakeAgents(), store, None)
    with pytest.raises(ValueError):
        MatchOrchestrator("m", None, FakeAgents(), store, None)


def test_test_doubles_stay_out_of_the_runtime():
    """Doubles live in tests/doubles/ and developer code in devtools/: no runtime module imports either, and the
    image holds only the package."""
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    package = root / "narrative_engine"
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(n.split(".")[0] in ("devtools", "doubles", "tests") or n.endswith(".fake") for n in names), path
    assert not (package / "devtools").exists() and not (package / "agents" / "fake.py").exists()
    assert "!narrative_engine/" in (root / ".dockerignore").read_text().splitlines()
