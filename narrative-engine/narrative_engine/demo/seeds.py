"""Demo seeds (PLAN.md §10.6): export one match's match-level documents, or load them under a new matchId.

Restore writes documents in the shapes the orchestrator writes and registers the match as known, so the
engine carries on as if it had run since kick-off; no core code knows a demo exists. Viewers' follow
decisions and narratives are never part of a seed."""
import asyncio
import copy
import hashlib
import hmac
import json
import logging
from dataclasses import asdict, fields

log = logging.getLogger("narrative_engine.demo")
SEED_STORES = ("checkpoints", "contextBlocks", "narratives", "analyses", "storylines")
PATHS = ("/admin/matches/export", "/admin/matches/restore")
# Bump when the checkpoint, analysis or storyline documents (plain dicts) change shape; the dataclass-backed
# documents are fingerprinted from their fields.
DOCUMENT_VERSION = 1
COSMOS_SYSTEM = ("_rid", "_self", "_etag", "_attachments", "_ts")
BATCH_DOCUMENTS = 100  # Cosmos's limit on operations in one transactional batch
BATCH_BYTES = 1_500_000  # under Cosmos's 2 MB request limit for one batch (an analysis document is ~60 KB)


class SeedRefused(ValueError):
    pass


def schema():
    """Fingerprint of the seeded document shapes: a seed restores only into the engine it came from."""
    from narrative_engine.core.models import ContextBlock, MatchClock, Narrative, Trigger
    shapes = [DOCUMENT_VERSION, SEED_STORES, *([f.name for f in fields(c)]
                                               for c in (ContextBlock, MatchClock, Narrative, Trigger))]
    return hashlib.sha256(json.dumps(shapes).encode()).hexdigest()[:16]


def _cosmos(store):
    return {"checkpoints": store.checkpoints, "contextBlocks": store.blocks, "narratives": store.items,
            "analyses": store.analysis_docs, "storylines": store.storyline_docs}


async def export(store, match_id):
    from narrative_engine.store.memory import MemoryStore
    if not isinstance(store, MemoryStore):  # without Cosmos system properties: the restore writes new documents
        return {name: [{k: v for k, v in doc.items() if k not in COSMOS_SYSTEM}
                       for doc in await store._query(container, match_id, "SELECT * FROM c WHERE c.matchId = @m")]
                for name, container in _cosmos(store).items()}
    from narrative_engine.transport.files import narrative_doc
    checkpoint = store.checkpoints.get(match_id)
    return {"checkpoints": [{**copy.deepcopy(checkpoint), "id": match_id, "matchId": match_id}] if checkpoint else [],
            "contextBlocks": [asdict(b) for b in store.blocks.values() if b.matchId == match_id],
            "narratives": [narrative_doc(n) for n in store.items.values() if n.matchId == match_id],
            "analyses": [copy.deepcopy(d) for d in store.analysis_docs.values() if d["matchId"] == match_id],
            "storylines": [copy.deepcopy(d) for d in store.storyline_docs.values() if d["matchId"] == match_id]}


def batches(docs):
    """Consecutive runs of documents within one transactional batch's operation and size limits."""
    batch, size = [], 0
    for doc in docs:
        length = len(json.dumps(doc))
        if batch and (len(batch) == BATCH_DOCUMENTS or size + length > BATCH_BYTES):
            yield batch
            batch, size = [], 0
        batch.append(doc)
        size += length
    if batch:
        yield batch


async def _load(store, match_id, containers):
    from narrative_engine.store.memory import MemoryStore
    if not isinstance(store, MemoryStore):
        # Every document of a match shares its partition (matchId), so each container takes transactional batches
        # instead of one round trip per document; the checkpoint goes last, so the match only looks known once
        # everything it refers to is in place.
        by_name = _cosmos(store)

        async def write(name, docs):
            for batch in batches(docs):
                await by_name[name].execute_item_batch([("upsert", (doc,)) for doc in batch], partition_key=match_id)
        await asyncio.gather(*(write(name, docs) for name, docs in containers.items() if name != "checkpoints"))
        await write("checkpoints", containers.get("checkpoints", []))
        return {name: len(docs) for name, docs in containers.items()}
    from narrative_engine.core.models import ContextBlock, MatchClock
    from narrative_engine.transport.files import narrative_from_doc
    for doc in containers.get("checkpoints", []):
        store.checkpoints[match_id] = {k: v for k, v in copy.deepcopy(doc).items() if k not in ("id", "matchId")}
    for doc in containers.get("contextBlocks", []):
        clocks = {k: MatchClock(**doc[k]) if doc.get(k) else None for k in ("coversFrom", "coversTo", "statsTime")}
        block = ContextBlock(**{**doc, **clocks})
        store.blocks[block.id] = block
    for doc in containers.get("narratives", []):
        narrative = narrative_from_doc(doc)
        store.items[narrative.id] = narrative
    for name, target in (("analyses", store.analysis_docs), ("storylines", store.storyline_docs)):
        for doc in containers.get(name, []):
            target[doc["id"]] = copy.deepcopy(doc)
    return {name: len(docs) for name, docs in containers.items()}


def _clock(text):
    """'1-019' -> (1, 19); None for anything else."""
    try:
        period, minute = str(text).split("-")
        return int(period), int(minute)
    except ValueError:
        return None


def past_seq(containers, max_seq):
    """Which restored documents reach past the seed's seq, or None. Narratives, analyses and queued steps carry
    the seq they were written from; storylines may only cite seeded analyses; summaries may only cover minutes
    the checkpoint has closed."""
    for name in ("narratives", "analyses"):
        if any((doc.get("eventSeq") or 0) > max_seq for doc in containers.get(name, [])):
            return name
    checkpoints = containers.get("checkpoints", [])
    if any((p.get("seq") or 0) > max_seq for doc in checkpoints for p in doc.get("pending", [])):
        return "queued steps"
    analyses = {doc["id"] for doc in containers.get("analyses", [])}
    for line in containers.get("storylines", []):
        cited = {line.get("openedBy"), line.get("lastAnalysisId"), *(b.get("analysisId") for b in line.get("beats", []))}
        if cited - {None} - analyses:
            return "storylines"
    closed = max((c for c in (_clock(doc.get("closedThrough")) for doc in checkpoints) if c), default=None)
    for block in containers.get("contextBlocks", []):
        end = block.get("coversTo") or {}
        if closed is None or (end.get("periodId", 0), end.get("timeMin", 0)) > closed:
            return "summaries"
    return None


async def restore(router, match_id, containers, max_seq, seed_schema):
    """Load a seed under a new matchId. The checkpoint's follow state is cleared, so follows made on this run
    start fresh. Refused for another schema, a known or purged match, documents of another match or
    narratives written from events past the seed's seq."""
    if seed_schema != schema():
        raise SeedRefused("The seed was exported from another engine schema; record it again")
    if match_id in router.purged or match_id in router.engines or await router.store.get_checkpoint(match_id):
        raise SeedRefused(f"{match_id} is already known or purged")
    if set(containers) - set(SEED_STORES):
        raise SeedRefused(f"Unknown containers {sorted(set(containers) - set(SEED_STORES))}")
    if any(doc.get("matchId") != match_id for docs in containers.values() for doc in docs):
        raise SeedRefused("The seed holds documents of another match")
    past = past_seq(containers, max_seq)
    if past:
        raise SeedRefused(f"{past} past the seed's seq")
    for doc in containers.get("checkpoints", []):
        doc.update(follows=None, followPairs=[], followFired={}, followRetries=[],
                   pending=[p for p in doc.get("pending", []) if not str(p.get("type", "")).startswith("subscription")])
    counts = await _load(router.store, match_id, containers)
    router.engine(match_id)  # known: its next notification is handled without the cut-off check
    log.info("restored %s %s", match_id, counts)
    return {"match_id": match_id, "restored": counts}


def seed_app(inner, router, admin_token=None):
    """ASGI in front of the service app: `POST /admin/matches/export|restore`, everything else passes through."""
    expected = f"Bearer {admin_token}".encode() if admin_token else None

    async def respond(send, status, body):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": json.dumps(body).encode()})

    async def app(scope, receive, send):
        path = scope.get("path")
        if scope["type"] != "http" or path not in PATHS:
            return await inner(scope, receive, send)
        if scope.get("method") != "POST":
            return await respond(send, 405, {"detail": "method not allowed"})
        if expected and not hmac.compare_digest(dict(scope["headers"]).get(b"authorization", b""), expected):
            return await respond(send, 401, {"detail": "unauthorized"})
        body, more = b"", True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        try:
            request = json.loads(body or b"{}")
            match_id = request["match_id"]
            if not isinstance(match_id, str) or not 0 < len(match_id) <= 64:
                raise ValueError
            if path.endswith("/export"):
                return await respond(send, 200, {"match_id": match_id, "schema": schema(),
                                                 "containers": await export(router.store, match_id)})
            containers, max_seq, seed_schema = request["containers"], request["max_seq"], request["schema"]
            if not isinstance(containers, dict) or not isinstance(max_seq, int) or not isinstance(seed_schema, str):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            return await respond(send, 422, {"detail": 'send {"match_id"} (export) or '
                                                       '{"match_id", "max_seq", "schema", "containers"}'})
        try:
            return await respond(send, 200, await restore(router, match_id, containers, max_seq, seed_schema))
        except SeedRefused as exc:
            return await respond(send, 409, {"detail": str(exc)})
        except Exception:
            log.exception("restore of %s failed", match_id)
            return await respond(send, 503, {"detail": "restore failed; retry"})

    return app
