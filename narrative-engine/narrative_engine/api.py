"""Narrative history GraphQL API (read-only), served from the engine's store.

Live narratives go out on Service Bus; this API is for joins and reconnects: a bucket's
backlog after a known `seq`, and the match's current state. See contracts/README.md.

    python -m narrative_engine.api .local/narratives.jsonl --port 8000   # serve a local run's output
"""
import argparse
from typing import Optional

import strawberry
from strawberry.asgi import GraphQL
from strawberry.types import Info

from narrative_engine.core.config import Settings
from narrative_engine.core.models import USER_TYPES, MatchClock
from narrative_engine.core.orchestrator import active_user_types, utcnow

MAX_PAGE = 200


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
    triggerType: str = strawberry.field(description="keyEvent, scheduled, halfTime, fullTime or catchUp.")
    triggerReason: str
    matchTime: MatchTime
    text: str
    model: Optional[str]
    promptVersion: Optional[str]
    createdAt: str

    @classmethod
    def of(cls, n):
        return cls(id=n.id, matchId=n.matchId, userType=n.userType, seq=n.seq, stepId=n.stepId,
                   triggerType=n.trigger.type, triggerReason=n.trigger.reason, matchTime=MatchTime.of(n.matchTime),
                   text=n.text, model=n.model, promptVersion=n.promptVersion, createdAt=n.createdAt)


@strawberry.type
class NarrativePage:
    items: list[Narrative]
    hasNextPage: bool
    endCursor: Optional[int] = strawberry.field(description="Last seq in this page; pass as afterSeq for the next.")


@strawberry.type
class MatchState:
    matchId: str
    status: str = strawberry.field(description="live or complete.")
    lastSummarised: Optional[MatchTime]
    activeUserTypes: list[str] = strawberry.field(
        description="Buckets narratives are being written for: those with viewers, or all 12 without fresh presence.")


@strawberry.type
class Query:
    @strawberry.field(description="One bucket's narratives with seq > afterSeq, oldest first.")
    async def narratives(self, info: Info, matchId: str, userType: str, afterSeq: int = 0,
                         first: int = 50) -> NarrativePage:
        if userType not in USER_TYPES:
            raise ValueError(f"userType must be one of {', '.join(USER_TYPES)}")
        if not 1 <= first <= MAX_PAGE:
            raise ValueError(f"first must be between 1 and {MAX_PAGE}")
        found = await info.context["store"].narratives_after(matchId, userType, afterSeq, first + 1)
        items = [Narrative.of(n) for n in found[:first]]
        return NarrativePage(items=items, hasNextPage=len(found) > first, endCursor=items[-1].seq if items else None)

    @strawberry.field(description="The engine's progress through a match; null before its first notification.")
    async def matchState(self, info: Info, matchId: str) -> Optional[MatchState]:
        cp = await info.context["store"].get_checkpoint(matchId)
        if cp is None:
            return None
        last = MatchClock.parse(cp["lastSummarised"]) if cp["lastSummarised"] else None
        active = active_user_types(cp, info.context["now"](), info.context["settings"].presence_stale_seconds)
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
    parser.add_argument("narratives", nargs="+", help="narrative JSONL files written by narrative_engine.devtools.local")
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
