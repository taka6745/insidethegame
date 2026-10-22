"""Cosmos DB store: containers checkpoints, contextBlocks, narratives, analyses, storylines,
subscriptionDecisions, subscriptionNarratives and tombstones, all partitioned
by /matchId, so every read and write stays inside one match's partition (except the startup and
purge-all reads). The purge-all cut-off is the tombstone document `ALL`.

Auth is Entra ID (DefaultAzureCredential: `az login` locally, managed identity in Azure), or a
key for the local emulator, which `open` also provisions (database and containers).
"""
import contextlib
from dataclasses import asdict

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError

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


CONTAINERS = ("checkpoints", "contextBlocks", "narratives", "analyses", "storylines", "subscriptionDecisions",
              "subscriptionNarratives", "tombstones")
ALL = "*all*"  # the purge-all cut-off's id and partition; not a valid matchId


class CosmosStore:
    def __init__(self, endpoint, credential=None, database="narrative", key=None):
        if key:  # the emulator: one fixed endpoint, so no endpoint discovery
            credential = key
            self.client = CosmosClient(endpoint, credential=key, enable_endpoint_discovery=False)
        else:
            if credential is None:
                from azure.identity.aio import DefaultAzureCredential
                credential = DefaultAzureCredential()
            self.client = CosmosClient(endpoint, credential=credential)
        self.credential, self.database = credential, database
        db = self.client.get_database_client(database)
        self.checkpoints = db.get_container_client("checkpoints")
        self.blocks = db.get_container_client("contextBlocks")
        self.items = db.get_container_client("narratives")
        self.analysis_docs = db.get_container_client("analyses")
        self.storyline_docs = db.get_container_client("storylines")
        self.decision_docs = db.get_container_client("subscriptionDecisions")
        self.follow_items = db.get_container_client("subscriptionNarratives")
        self.purges = db.get_container_client("tombstones")

    @classmethod
    async def open(cls, endpoint, key=None, database="narrative"):
        store = cls(endpoint, database=database, key=key)
        if key:  # Terraform provisions Azure; the emulator starts empty
            db = await store.client.create_database_if_not_exists(database)
            for name in CONTAINERS:
                await db.create_container_if_not_exists(name, PartitionKey("/matchId"))
        return store

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

    async def put_analysis(self, analysis):
        with contextlib.suppress(CosmosResourceExistsError):  # immutable: the first write stands
            await self.analysis_docs.create_item(analysis)

    async def get_analysis(self, match_id, analysis_id):
        try:
            return _clean(await self.analysis_docs.read_item(analysis_id, partition_key=match_id))
        except CosmosResourceNotFoundError:
            return None

    async def analyses(self, match_id):
        docs = await self._query(self.analysis_docs, match_id, "SELECT * FROM c WHERE c.matchId = @m")
        return sorted(docs, key=lambda d: d["horizon"])

    async def put_storylines(self, match_id, storylines):
        for line in storylines:
            await self.storyline_docs.upsert_item(line)

    async def storylines(self, match_id):
        docs = await self._query(self.storyline_docs, match_id, "SELECT * FROM c WHERE c.matchId = @m")
        return sorted(docs, key=lambda d: d["n"])

    async def put_decision(self, decision):
        with contextlib.suppress(CosmosResourceExistsError):  # immutable: the first answer stands
            await self.decision_docs.create_item(decision)

    async def get_decision(self, match_id, decision_id):
        try:
            return _clean(await self.decision_docs.read_item(decision_id, partition_key=match_id))
        except CosmosResourceNotFoundError:
            return None

    async def decisions(self, match_id):
        docs = await self._query(self.decision_docs, match_id, "SELECT * FROM c WHERE c.matchId = @m")
        return sorted(docs, key=lambda d: (d["horizon"], d["id"]))

    async def add_subscription_narrative(self, narrative):
        await self.follow_items.upsert_item(narrative_doc(narrative))

    async def subscription_narratives(self, match_id, topic_id=None, user_type=None):
        query, params = "SELECT * FROM c WHERE c.matchId = @m", {}
        if topic_id is not None:
            query, params = query + " AND c.topicId = @t", params | {"t": topic_id}
        if user_type is not None:
            query, params = query + " AND c.userType = @u", params | {"u": user_type}
        docs = await self._query(self.follow_items, match_id, query, **params)
        return sorted((narrative_from_doc(d) for d in docs), key=lambda n: (n.createdAt, n.topicId, n.userType, n.seq))

    async def subscription_narratives_after(self, match_id, topic_id, user_type, after_seq, limit):
        docs = await self._query(
            self.follow_items, match_id, "SELECT * FROM c WHERE c.matchId = @m AND c.topicId = @t AND c.userType = @u "
            "AND c.seq > @s ORDER BY c.seq OFFSET 0 LIMIT @n", t=topic_id, u=user_type, s=after_seq, n=limit)
        return [narrative_from_doc(d) for d in docs]

    async def subscription_narrative_for_step(self, match_id, topic_id, user_type, step_id):
        docs = await self._query(self.follow_items, match_id, "SELECT * FROM c WHERE c.matchId = @m AND c.topicId = @t "
                                 "AND c.userType = @u AND c.stepId = @s", t=topic_id, u=user_type, s=step_id)
        return narrative_from_doc(docs[0]) if docs else None

    async def live_match_ids(self):
        query = self.checkpoints.query_items(
            "SELECT VALUE c.matchId FROM c WHERE c.status = 'live' OR ARRAY_LENGTH(c.pending) > 0")
        return sorted([m async for m in query])

    async def delete_match(self, match_id):
        """Remove one match's documents (tombstones stay); returns how many per container."""
        counts = {}
        for name, container in (("checkpoints", self.checkpoints), ("contextBlocks", self.blocks),
                                ("narratives", self.items), ("analyses", self.analysis_docs),
                                ("storylines", self.storyline_docs), ("subscriptionDecisions", self.decision_docs),
                                ("subscriptionNarratives", self.follow_items)):
            docs = await self._query(container, match_id, "SELECT c.id FROM c WHERE c.matchId = @m")
            for doc in docs:
                with contextlib.suppress(CosmosResourceNotFoundError):
                    await container.delete_item(doc["id"], partition_key=match_id)
            counts[name] = len(docs)
        return counts

    async def match_ids(self):
        return sorted({m async for m in self.checkpoints.query_items("SELECT VALUE c.matchId FROM c")})

    async def add_tombstones(self, match_ids, cutoff=None):
        for match_id in match_ids:
            await self.purges.upsert_item({"id": match_id, "matchId": match_id})
        if cutoff:
            _, current = await self.tombstones()
            if current is None or cutoff > current:
                await self.purges.upsert_item({"id": ALL, "matchId": ALL, "cutoff": cutoff})

    async def tombstones(self):
        docs = [d async for d in self.purges.query_items("SELECT c.matchId, c.cutoff FROM c")]
        return {d["matchId"] for d in docs if d["matchId"] != ALL}, \
            next((d["cutoff"] for d in docs if d["matchId"] == ALL), None)
