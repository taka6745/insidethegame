"""Cosmos DB store: containers checkpoints, contextBlocks and narratives, all partitioned by
/matchId, so every read and write stays inside one match's partition.

Auth is Entra ID only (DefaultAzureCredential: `az login` locally, managed identity in Azure).
"""
from dataclasses import asdict

from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from narrative_engine.core.models import ContextBlock, MatchClock
from narrative_engine.transport.files import narrative_doc, narrative_from_doc


def _clean(doc):
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def block_doc(block):
    return asdict(block)


def block_from_doc(doc):
    doc = _clean(doc)
    clocks = {k: MatchClock(**doc[k]) if doc.get(k) else None for k in ("coversFrom", "coversTo", "statsTime")}
    return ContextBlock(**{**doc, **clocks})


class CosmosStore:
    def __init__(self, endpoint, credential=None, database="narrative"):
        if credential is None:
            from azure.identity.aio import DefaultAzureCredential
            credential = DefaultAzureCredential()
        self.credential = credential
        self.client = CosmosClient(endpoint, credential=credential)
        db = self.client.get_database_client(database)
        self.checkpoints = db.get_container_client("checkpoints")
        self.blocks = db.get_container_client("contextBlocks")
        self.items = db.get_container_client("narratives")

    async def aclose(self):
        await self.client.close()
        if hasattr(self.credential, "close"):
            await self.credential.close()

    async def _query(self, container, match_id, query, **params):
        parameters = [{"name": "@m", "value": match_id}] + [{"name": f"@{k}", "value": v} for k, v in params.items()]
        return [_clean(d) async for d in container.query_items(query, parameters=parameters, partition_key=match_id)]

    async def get_checkpoint(self, match_id):
        try:
            doc = await self.checkpoints.read_item(match_id, partition_key=match_id)
        except CosmosResourceNotFoundError:
            return None
        return {k: v for k, v in _clean(doc).items() if k not in ("id", "matchId")}

    async def save_checkpoint(self, match_id, checkpoint):
        await self.checkpoints.upsert_item({**checkpoint, "id": match_id, "matchId": match_id})

    async def put_block(self, block):
        await self.blocks.upsert_item(block_doc(block))

    async def supersede(self, block, input_ids):
        """The new block and its inputs' supersededBy, in one transactional batch."""
        operations = [("upsert", (block_doc(block),))] + [
            ("patch", (block_id, [{"op": "set", "path": "/supersededBy", "value": block.id}])) for block_id in input_ids]
        await self.blocks.execute_item_batch(operations, partition_key=block.matchId)

    async def active_blocks(self, match_id):
        docs = await self._query(self.blocks, match_id,
                                 "SELECT * FROM c WHERE c.matchId = @m AND IS_NULL(c.supersededBy)")
        return sorted((block_from_doc(d) for d in docs), key=lambda b: b.coversFrom)

    async def all_blocks(self, match_id):
        """Every block, superseded ones included (reports)."""
        docs = await self._query(self.blocks, match_id, "SELECT * FROM c WHERE c.matchId = @m")
        return [block_from_doc(d) for d in docs]

    async def add_narrative(self, narrative):
        await self.items.upsert_item(narrative_doc(narrative))

    async def narratives(self, match_id, user_type=None):
        if user_type is None:
            docs = await self._query(self.items, match_id, "SELECT * FROM c WHERE c.matchId = @m")
        else:
            docs = await self._query(self.items, match_id, "SELECT * FROM c WHERE c.matchId = @m AND c.userType = @u",
                                     u=user_type)
        return sorted((narrative_from_doc(d) for d in docs), key=lambda n: (n.createdAt, n.userType, n.seq))

    async def narratives_after(self, match_id, user_type, after_seq, limit):
        docs = await self._query(
            self.items, match_id,
            "SELECT * FROM c WHERE c.matchId = @m AND c.userType = @u AND c.seq > @s ORDER BY c.seq OFFSET 0 LIMIT @n",
            u=user_type, s=after_seq, n=limit)
        return [narrative_from_doc(d) for d in docs]

    async def narrative_for_step(self, match_id, user_type, step_id):
        docs = await self._query(self.items, match_id,
                                 "SELECT * FROM c WHERE c.matchId = @m AND c.userType = @u AND c.stepId = @s",
                                 u=user_type, s=step_id)
        return narrative_from_doc(docs[0]) if docs else None

    async def live_match_ids(self):
        query = self.checkpoints.query_items("SELECT VALUE c.matchId FROM c WHERE c.status = 'live'")
        return sorted([m async for m in query])

    async def delete_match(self, match_id):
        """Remove one match's documents (tests and re-runs)."""
        for container in (self.checkpoints, self.blocks, self.items):
            for doc in await self._query(container, match_id, "SELECT c.id FROM c WHERE c.matchId = @m"):
                await container.delete_item(doc["id"], partition_key=match_id)
