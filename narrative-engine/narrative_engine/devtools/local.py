"""Run the engine locally over an ETL notifications file.

    python -m narrative_engine.devtools.local ../etl/.local/notifications.jsonl --pace 5
    python -m narrative_engine.devtools.local ../etl/.local/notifications.jsonl --data graphql
    python -m narrative_engine.devtools.local ../etl/.local/notifications.jsonl --agents llm --presence '{"home:casual": 1}'
    python -m narrative_engine.devtools.local ../etl/.local/notifications.jsonl --pace 5 --serve 8000

Data comes from a replay file (default) or the ETL's GraphQL API. Agents are fakes unless
`--agents llm` (settings in .env). Narratives go to .local/narratives.jsonl, context blocks
to .local/blocks.jsonl. `--serve PORT` also serves the narrative GraphQL API during and
after the run.
"""
import argparse
import asyncio
import json
import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import httpx

from narrative_engine.agents.fake import FakeAgents
from narrative_engine.agents.llm import LLMAgents, LLMError, LLMSettings
from narrative_engine.api import NarrativeApi
from narrative_engine.core.config import Settings
from narrative_engine.match_data.etl_graphql import GraphQLMatchData
from narrative_engine.match_data.fixture import FixtureMatchData
from narrative_engine.core.models import PresenceChanged
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import JsonlSink, read_notifications, replay

HERE = Path(__file__).resolve().parents[2]
DEFAULT_MATCH = HERE.parent / "etl" / "seeder" / "matches" / "itg-syn-0001.jsonl"


async def run(args):
    match_id = args.match_id or next(b["matchId"] for b, _ in read_notifications(args.notifications))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("")
    if args.data == "graphql":
        data = GraphQLMatchData(args.graphql_url)
    else:
        data = FixtureMatchData(args.match, args.notifications)
    agents = LLMAgents(LLMSettings.from_env()) if args.agents == "llm" else FakeAgents()
    store = MemoryStore()
    # A local run's fixed --presence must not go stale part-way through a slow LLM run.
    settings = Settings(presence_stale_seconds=10 ** 9) if args.presence else Settings()
    engine = MatchOrchestrator(match_id, data, agents, store, JsonlSink(out), settings)
    if args.serve:
        import uvicorn
        server = uvicorn.Server(uvicorn.Config(NarrativeApi(store, settings, engine.now), port=args.serve,
                                               log_level="warning"))
        serving = asyncio.create_task(server.serve())
        print(f"narrative GraphQL at http://localhost:{args.serve}/graphql")
    if args.presence:
        counts = json.loads(args.presence)
        await engine.handle(PresenceChanged(match_id, counts, engine.now()))
        print(f"presence: {counts}")
    await replay(args.notifications, engine.handle, pace=args.pace, match_id=match_id)
    narratives = await store.narratives(match_id)
    blocks = await store.active_blocks(match_id)
    with open(out.with_name("blocks.jsonl"), "w") as f:
        for b in store.blocks.values():
            f.write(json.dumps(asdict(b), default=str) + "\n")
    print(f"{len(narratives)} narratives written to {out}")
    print("steps:", dict(Counter(n.trigger.type for n in narratives)))
    print("context:", [f"{b.coversFrom.label}-{b.coversTo.label}" for b in blocks])
    if args.serve:
        print("still serving; Ctrl+C to stop")
        await serving


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notifications", help="ETL notifications JSONL (the ETL's `python -m devtools load-local` writes one)")
    parser.add_argument("--data", choices=("fixture", "graphql"), default="fixture")
    parser.add_argument("--agents", choices=("fake", "llm"), default="fake")
    parser.add_argument("--graphql-url", default=os.environ.get("ETL_GRAPHQL_URL", "http://localhost:5000/graphql"))
    parser.add_argument("--match", default=str(DEFAULT_MATCH), help="replay/match JSONL for --data fixture")
    parser.add_argument("--match-id", help="defaults to the notifications' matchId")
    parser.add_argument("--pace", type=float, default=0.0,
                        help="0 = sequential and as fast as possible; N = N times the recorded timing, concurrent")
    parser.add_argument("--presence", help='JSON bucket counts, e.g. \'{"home:casual": 1}\'; default all 12')
    parser.add_argument("--serve", type=int, metavar="PORT", help="serve the narrative GraphQL API on this port")
    parser.add_argument("--out", default=str(HERE / ".local" / "narratives.jsonl"))
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except httpx.ConnectError:
        raise SystemExit(f"ETL GraphQL not reachable at {args.graphql_url}; start it with `python -m devtools local-up` in etl/")
    except LLMError as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    main()
