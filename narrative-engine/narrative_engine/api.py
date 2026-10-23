"""Narrative history GraphQL API (read-only), served from the engine's store: a bucket's backlog after a known
`seq` and the match's current state, for joins and reconnects. See contracts/README.md.

    python -m narrative_engine.api .local/narratives.jsonl --port 8000   # serve a local run's output
"""
import argparse
import re
from typing import Optional

import strawberry
from strawberry.asgi import GraphQL
from strawberry.types import Info

from narrative_engine.context.compression import TIERS
from narrative_engine.core.config import Settings
from narrative_engine.core.models import MatchClock
from narrative_engine.core.orchestrator import active_user_types, utcnow

MAX_PAGE = 200
BUCKET_ID = re.compile(r"^[a-z0-9][a-z0-9_:-]{0,99}$")  # the user backend's audience catalogue ids
TOPIC_ID = re.compile(r"^topic:[0-9a-f]{16}$")  # the user backend's followed-topic ids


@strawberry.type
class MatchTime:
    periodId: int
    timeMin: int
    label: str

    @classmethod
    def of(cls, clock):
        return cls(periodId=clock.periodId, timeMin=clock.timeMin, label=clock.label)


@strawberry.type
class Narrative:
    id: str
    matchId: str
    userType: str
    seq: int
    stepId: str = strawberry.field(description="Shared by every bucket's version of the same narrative step.")
    triggerType: str = strawberry.field(description="keyEvent, scheduled, storylineTurn, halfTime, fullTime or catchUp.")
    triggerReason: str
    matchTime: MatchTime
    text: str
    model: Optional[str]
    promptVersion: Optional[str]
    createdAt: str
    timeSec: Optional[int] = strawberry.field(description="Second of matchTime the step's data reaches.")
    audienceRevision: Optional[int] = strawberry.field(description="User-backend audience revision of the bucket.")
    eventSeq: Optional[int] = strawberry.field(
        description="Latest canonical MatchEvent seq in the data the narrative was written from (show it at snapshot seq >= this).")
    analysisId: Optional[str] = strawberry.field(description="The match analysis whose storylines the step read.")
    storylineIds: list[str] = strawberry.field(description="The storyline this narrative advances (its focus), if any.")

    @classmethod
    def of(cls, n):
        return cls(id=n.id, matchId=n.matchId, userType=n.userType, seq=n.seq, stepId=n.stepId,
                   triggerType=n.trigger.type, triggerReason=n.trigger.reason, matchTime=MatchTime.of(n.matchTime),
                   text=n.text, model=n.model, promptVersion=n.promptVersion, createdAt=n.createdAt,
                   timeSec=n.timeSec, audienceRevision=n.audienceRevision, eventSeq=n.eventSeq,
                   analysisId=n.analysisId, storylineIds=list(n.storylineIds or []))


@strawberry.type
class FollowDecision:
    score: Optional[float] = strawberry.field(description="The decision model's level for how far the update moved the story.")
    confidence: Optional[float]
    novelty: Optional[float] = strawberry.field(description="P(a new development since the topic's last narrative); null if not asked.")
    model: Optional[str]


@strawberry.type
class SubscriptionNarrative(Narrative):
    topicId: str
    decision: Optional[FollowDecision] = strawberry.field(description="Why it fired; null for a catchUp (the story so far).")

    @classmethod
    def of(cls, n):
        d = n.decision
        return cls(**vars(Narrative.of(n)), topicId=n.topicId, decision=d and FollowDecision(
            score=d.get("score"), confidence=d.get("confidence"), novelty=d.get("novelty"), model=d.get("model")))


@strawberry.type
class SubscriptionNarrativePage:
    items: list[SubscriptionNarrative]
    hasNextPage: bool
    endCursor: Optional[int] = strawberry.field(description="Last seq in this page; pass as afterSeq for the next.")


@strawberry.type
class NarrativePage:
    items: list[Narrative]
    hasNextPage: bool
    endCursor: Optional[int] = strawberry.field(description="Last seq in this page; pass as afterSeq for the next.")


@strawberry.type
class ContextBlock:
    id: str
    matchId: str
    level: int = strawberry.field(description="0 one-minute summary, 1 five-minute block, 2 earlier or whole-period block.")
    tier: str = strawberry.field(description="minute, five-minute, twenty-minute (an earlier block) or half (a whole period).")
    coversFrom: MatchTime
    coversTo: MatchTime
    summary: str
    supersededBy: Optional[str] = strawberry.field(description="The block that replaced this one in the context.")
    createdAt: str

    @classmethod
    def of(cls, b):
        return cls(id=b.id, matchId=b.matchId, level=b.level, tier=b.tier or TIERS[b.level], coversFrom=MatchTime.of(b.coversFrom),
                   coversTo=MatchTime.of(b.coversTo), summary=b.summary, supersededBy=b.supersededBy,
                   createdAt=b.createdAt)


@strawberry.type
class StorylineBeat:
    at: MatchTime
    headline: str
    explanation: Optional[str]
    confidence: float
    analysisId: str


@strawberry.type
class StorylineSalience:
    at: MatchTime
    salience: float


@strawberry.type
class StorylineResolution:
    at: MatchTime
    outcome: str


@strawberry.type
class Storyline:
    id: str
    matchId: str
    label: str = strawberry.field(description="The analyst's own name for the thread.")
    team: Optional[str] = strawberry.field(description="Contestant id it is about; null for both teams.")
    status: str = strawberry.field(description="active, dormant or resolved.")
    salience: float = strawberry.field(description="The latest; salienceHistory has it as of each analysis.")
    salienceHistory: list[StorylineSalience] = strawberry.field(
        description="Salience after each analysis that changed it, oldest first.")
    openedAt: MatchTime
    updatedAt: MatchTime
    resolvedAt: Optional[MatchTime]
    outcome: Optional[str]
    resolutions: list[StorylineResolution] = strawberry.field(
        description="Earlier resolutions of a storyline that reopened (storylines.reopen_within), oldest first.")
    beats: list[StorylineBeat]
    keyEventIds: list[int] = strawberry.field(description="ETL keyEvents ids linked to it by rule.")

    @classmethod
    def of(cls, d):
        clock = lambda c: c and MatchTime(periodId=c["periodId"], timeMin=c["timeMin"], label=c["label"])
        return cls(id=d["id"], matchId=d["matchId"], label=d["label"], team=d["team"], status=d["status"],
                   salience=d["salience"], openedAt=clock(d["openedAt"]),
                   salienceHistory=[StorylineSalience(at=clock(h["at"]), salience=h["salience"])
                                    for h in d.get("salienceHistory", [])], updatedAt=clock(d["updatedAt"]),
                   resolvedAt=clock(d["resolvedAt"]), outcome=d["outcome"], keyEventIds=d["keyEventIds"],
                   resolutions=[StorylineResolution(at=clock(r["at"]), outcome=r["outcome"])
                                for r in d.get("resolutions", [])],
                   beats=[StorylineBeat(at=clock(b["at"]), headline=b["headline"], explanation=b.get("explanation"),
                                        confidence=b["confidence"], analysisId=b["analysisId"]) for b in d["beats"]])


@strawberry.type
class MatchState:
    matchId: str
    status: str = strawberry.field(description="live or complete.")
    lastSummarised: Optional[MatchTime]
    activeUserTypes: list[str] = strawberry.field(
        description="Buckets narratives are being written for: the user backend's current generation targets.")


@strawberry.type
class Query:
    @strawberry.field(description="One bucket's narratives with seq > afterSeq, oldest first.")
    async def narratives(self, info: Info, matchId: str, userType: str, afterSeq: int = 0,
                         first: int = 50) -> NarrativePage:
        if not BUCKET_ID.match(userType):
            raise ValueError("userType must be an audience bucket id such as home:casual")
        if not 1 <= first <= MAX_PAGE:
            raise ValueError(f"first must be between 1 and {MAX_PAGE}")
        found = await info.context["store"].narratives_after(matchId, userType, afterSeq, first + 1)
        items = [Narrative.of(n) for n in found[:first]]
        return NarrativePage(items=items, hasNextPage=len(found) > first, endCursor=items[-1].seq if items else None)

    @strawberry.field(description="One followed topic's narratives for one bucket with seq > afterSeq, oldest first.")
    async def subscriptionNarratives(self, info: Info, matchId: str, topicId: str, userType: str, afterSeq: int = 0,
                                     first: int = 50) -> SubscriptionNarrativePage:
        if not BUCKET_ID.match(userType):
            raise ValueError("userType must be an audience bucket id such as home:casual")
        if not TOPIC_ID.match(topicId):
            raise ValueError("topicId must be a topic id such as topic:3fa2c1d0e4b5a697")
        if not 1 <= first <= MAX_PAGE:
            raise ValueError(f"first must be between 1 and {MAX_PAGE}")
        found = await info.context["store"].subscription_narratives_after(matchId, topicId, userType, afterSeq,
                                                                           first + 1)
        items = [SubscriptionNarrative.of(n) for n in found[:first]]
        return SubscriptionNarrativePage(items=items, hasNextPage=len(found) > first,
                                         endCursor=items[-1].seq if items else None)

    @strawberry.field(description="The match's context summaries (neutral, shared by every bucket), in match order.")
    async def contextBlocks(self, info: Info, matchId: str, includeSuperseded: bool = True) -> list[ContextBlock]:
        store = info.context["store"]
        blocks = await (store.all_blocks(matchId) if includeSuperseded else store.active_blocks(matchId))
        return [ContextBlock.of(b) for b in sorted(blocks, key=lambda b: (b.coversFrom, b.level))]

    @strawberry.field(description="The match's storylines (current state), in the order they opened.")
    async def storylines(self, info: Info, matchId: str) -> list[Storyline]:
        return [Storyline.of(d) for d in await info.context["store"].storylines(matchId)]

    @strawberry.field(description="The engine's progress through a match; null before its first notification.")
    async def matchState(self, info: Info, matchId: str) -> Optional[MatchState]:
        cp = await info.context["store"].get_checkpoint(matchId)
        if cp is None:
            return None
        last = MatchClock.parse(cp["lastSummarised"]) if cp["lastSummarised"] else None
        active = active_user_types(cp)
        return MatchState(matchId=matchId, status=cp["status"], lastSummarised=MatchTime.of(last) if last else None,
                          activeUserTypes=active)


schema = strawberry.Schema(query=Query)


class NarrativeApi(GraphQL):
    """ASGI app serving `schema` at any path; mount or run it with uvicorn."""

    def __init__(self, store, settings=Settings(), now=utcnow, **options):
        super().__init__(schema, allow_queries_via_get=False, **options)
        self.context = {"store": store, "settings": settings, "now": now}

    async def get_context(self, request, response):
        return self.context


def main():
    import asyncio

    import uvicorn

    from narrative_engine.store.memory import MemoryStore
    from narrative_engine.transport.files import read_narratives

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("narratives", nargs="+", help="narrative JSONL files written by devtools.local")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    store = MemoryStore()
    for path in args.narratives:
        for narrative in read_narratives(path):
            asyncio.run(store.add_narrative(narrative))
    print(f"{len(store.items)} narratives; GraphQL at http://localhost:{args.port}/graphql", flush=True)
    uvicorn.run(NarrativeApi(store), port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
