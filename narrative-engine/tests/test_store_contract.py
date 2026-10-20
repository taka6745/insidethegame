"""The same Store checks against the memory store and, when COSMOS_ENDPOINT is set (env or
.env) and `az login` works, the dev Cosmos DB account. Cosmos runs use a unique matchId and
delete their documents afterwards."""
import asyncio
import os
import uuid

import pytest

from narrative_engine.agents.llm import load_env
from narrative_engine.core.models import ContextBlock, MatchClock, Narrative, Trigger
from narrative_engine.core.orchestrator import new_checkpoint
from narrative_engine.store.memory import MemoryStore

load_env()


def block(match_id, level, start, end, summary="s"):
    return ContextBlock(f"block:{match_id}:{level}:{start.key}:{end.key}", match_id, level, start, end, summary, end,
                        "m", "p", {"total_tokens": 1}, "2026-10-19T00:00:00+00:00")


def narrative(match_id, user_type, seq, step):
    return Narrative(f"narr:{match_id}:{user_type}:{seq}", match_id, user_type, seq, f"{match_id}:{step}",
                     Trigger("keyEvent", step, "Goal", (1, 2)), MatchClock(1, seq), f"text {seq}", "m", "p", None,
                     f"2026-10-19T00:00:{seq:02d}+00:00")


def stores():
    yield "memory"
    if os.environ.get("COSMOS_ENDPOINT"):
        yield "cosmos"


@pytest.fixture(params=list(stores()))
def store(request):
    if request.param == "memory":
        yield MemoryStore(), f"m-{uuid.uuid4().hex[:8]}", asyncio.run
        return
    from narrative_engine.store.cosmos import CosmosStore
    loop = asyncio.new_event_loop()
    cosmos = CosmosStore(os.environ["COSMOS_ENDPOINT"])
    match_id = f"test-{uuid.uuid4().hex[:8]}"
    yield cosmos, match_id, loop.run_until_complete
    loop.run_until_complete(cosmos.delete_match(match_id))
    loop.run_until_complete(cosmos.aclose())
    loop.close()


def test_checkpoint_round_trip_keeps_json_types(store):
    s, m, run = store
    assert run(s.get_checkpoint(m)) is None
    cp = {**new_checkpoint(), "lastSummarised": "2-047", "horizon": [2, 47, 30], "periodEnds": {"1": "1-047"},
          "closedPeriods": [1], "presence": {"counts": {"home:casual": 2}, "sentAt": "x", "receivedAt": "y"}}
    run(s.save_checkpoint(m, cp))
    assert run(s.get_checkpoint(m)) == cp
    run(s.save_checkpoint(m, {**cp, "status": "complete"}))
    assert run(s.get_checkpoint(m))["status"] == "complete"


def test_blocks_upsert_supersede_and_order(store):
    s, m, run = store
    minutes = [block(m, 0, MatchClock(1, t), MatchClock(1, t)) for t in range(5)]
    for b in reversed(minutes):
        run(s.put_block(b))
    run(s.put_block(block(m, 0, MatchClock(1, 0), MatchClock(1, 0), "rewritten")))  # same id: overwrite
    active = run(s.active_blocks(m))
    assert [b.coversFrom for b in active] == [MatchClock(1, t) for t in range(5)] and active[0].summary == "rewritten"
    merged = block(m, 1, MatchClock(1, 0), MatchClock(1, 4), "five")
    run(s.supersede(merged, [b.id for b in minutes]))
    assert run(s.active_blocks(m)) == [merged]
    assert run(s.active_blocks("other-match")) == []


def test_narratives_by_bucket_page_and_step(store):
    s, m, run = store
    for seq in (1, 2, 3):
        for user_type in ("home:casual", "away:analyst"):
            run(s.add_narrative(narrative(m, user_type, seq, f"key:{seq}")))
    mine = run(s.narratives(m, "home:casual"))
    assert [n.seq for n in mine] == [1, 2, 3] and mine[0].trigger.eventIds == (1, 2)
    assert mine[0].matchTime == MatchClock(1, 1) and len(run(s.narratives(m))) == 6
    assert [n.seq for n in run(s.narratives_after(m, "home:casual", 1, 1))] == [2]
    assert [n.seq for n in run(s.narratives_after(m, "away:analyst", 1, 10))] == [2, 3]
    assert run(s.narrative_for_step(m, "away:analyst", f"{m}:key:2")).seq == 2
    assert run(s.narrative_for_step(m, "away:analyst", f"{m}:key:9")) is None
