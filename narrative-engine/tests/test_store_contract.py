"""The same Store checks against the memory store and, when COSMOS_ENDPOINT is set (env or
.env), Cosmos DB: the dev account with `az login`, or the local emulator with COSMOS_KEY. Cosmos runs use a unique matchId and
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
    cosmos = loop.run_until_complete(CosmosStore.open(os.environ["COSMOS_ENDPOINT"], key=os.environ.get("COSMOS_KEY")))
    match_id = f"test-{uuid.uuid4().hex[:8]}"
    yield cosmos, match_id, loop.run_until_complete
    loop.run_until_complete(cosmos.delete_match(match_id))
    loop.run_until_complete(cosmos.aclose())
    loop.close()


def test_checkpoint_round_trip_keeps_json_types(store):
    s, m, run = store
    assert run(s.get_checkpoint(m)) is None
    cp = {**new_checkpoint(), "lastSummarised": "2-047", "horizon": [2, 47, 30], "periodEnds": {"1": "1-047"},
          "closedPeriods": [1], "targets": {"revision": 2, "items": [{"bucket_id": "home:casual"}]},
          "periodEndSeconds": {"1": 12}}
    run(s.save_checkpoint(m, cp))
    assert run(s.get_checkpoint(m)) == cp
    assert m in run(s.live_match_ids())
    run(s.save_checkpoint(m, {**cp, "status": "complete", "pending": [{"ref": "fullTime:2"}]}))
    assert run(s.get_checkpoint(m))["status"] == "complete"
    assert m in run(s.live_match_ids())  # its full-time step still has to run after a restart
    run(s.save_checkpoint(m, {**cp, "status": "complete"}))
    assert m not in run(s.live_match_ids())


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


def test_tier_event_seq_delete_counts_and_tombstones(store):
    s, m, run = store
    run(s.save_checkpoint(m, new_checkpoint()))
    run(s.put_block(ContextBlock(**{**vars(block(m, 2, MatchClock(1, 0), MatchClock(1, 46))), "tier": "half"})))
    run(s.add_narrative(Narrative(**{**vars(narrative(m, "home:casual", 1, "key:1")), "eventSeq": 812})))
    assert [b.tier for b in run(s.all_blocks(m))] == ["half"]
    assert run(s.narratives(m))[0].eventSeq == 812
    assert m in run(s.match_ids())
    run(s.add_tombstones([m]))
    assert m in run(s.tombstones())[0]
    assert run(s.delete_match(m)) == {"checkpoints": 1, "contextBlocks": 1, "narratives": 1,
                                         "analyses": 0, "storylines": 0, "subscriptionDecisions": 0,
                                         "subscriptionNarratives": 0}
    assert run(s.delete_match(m)) == {"checkpoints": 0, "contextBlocks": 0, "narratives": 0,
                                         "analyses": 0, "storylines": 0, "subscriptionDecisions": 0,
                                         "subscriptionNarratives": 0}
    assert m not in run(s.match_ids()) and m in run(s.tombstones())[0]


def test_the_purge_all_cut_off_only_moves_forward():
    s = MemoryStore()
    asyncio.run(s.add_tombstones(["a"], "2026-10-20T10:00:00+00:00"))
    asyncio.run(s.add_tombstones(["b"], "2026-10-20T09:00:00+00:00"))
    assert asyncio.run(s.tombstones()) == ({"a", "b"}, "2026-10-20T10:00:00+00:00")


def test_follow_decisions_are_immutable_and_follow_narratives_page_per_topic_and_bucket(store):
    s, m, run = store
    decision = {"id": f"subdec:{m}:key:1", "matchId": m, "horizon": [1, 3, 10], "fired": ["topic:00000000000000aa"]}
    run(s.put_decision(decision))
    run(s.put_decision({**decision, "fired": []}))  # a second write never replaces the first answer
    assert run(s.get_decision(m, decision["id"]))["fired"] == decision["fired"]
    assert run(s.get_decision(m, "subdec:other")) is None and len(run(s.decisions(m))) == 1
    topic = "topic:00000000000000aa"
    for seq in (1, 2, 3):
        n = narrative(m, "home:casual", seq, f"sub:{topic}:key:{seq}")
        run(s.add_subscription_narrative(Narrative(**{**vars(n), "id": f"sub:{m}:{topic}:home:casual:{seq}",
                                                      "kind": "subscription", "topicId": topic,
                                                      "decision": {"score": 2.0, "confidence": 0.9}})))
    run(s.add_narrative(narrative(m, "home:casual", 1, "key:1")))
    page = run(s.subscription_narratives_after(m, topic, "home:casual", 1, 1))
    assert [n.seq for n in page] == [2] and page[0].kind == "subscription" and page[0].decision["score"] == 2.0
    assert run(s.subscription_narratives_after(m, "topic:00000000000000bb", "home:casual", 0, 5)) == []
    assert [n.seq for n in run(s.subscription_narratives(m, topic))] == [1, 2, 3]
    assert run(s.subscription_narrative_for_step(m, topic, "home:casual", f"{m}:sub:{topic}:key:2")).seq == 2
    assert [n.kind for n in run(s.narratives(m))] == ["bucket"]  # bucket insights stay apart
    counts = run(s.delete_match(m))
    assert (counts["subscriptionDecisions"], counts["subscriptionNarratives"], counts["narratives"]) == (1, 3, 1)
    assert run(s.subscription_narratives(m)) == [] and run(s.decisions(m)) == []
