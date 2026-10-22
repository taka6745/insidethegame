import copy


class MemoryStore:
    def __init__(self):
        self.checkpoints, self.blocks, self.items = {}, {}, {}
        self.analysis_docs, self.storyline_docs = {}, {}
        self.decision_docs, self.follow_items = {}, {}
        self.purged, self.cutoff = set(), None

    async def get_checkpoint(self, match_id):
        return copy.deepcopy(self.checkpoints.get(match_id))

    async def save_checkpoint(self, match_id, checkpoint):
        self.checkpoints[match_id] = copy.deepcopy(checkpoint)

    async def put_block(self, block):
        self.blocks[block.id] = copy.deepcopy(block)

    async def supersede(self, block, input_ids):
        await self.put_block(block)
        for block_id in input_ids:
            self.blocks[block_id].supersededBy = block.id

    async def active_blocks(self, match_id):
        active = [b for b in self.blocks.values() if b.matchId == match_id and b.supersededBy is None]
        return [copy.deepcopy(b) for b in sorted(active, key=lambda b: b.coversFrom)]

    async def all_blocks(self, match_id):
        """Every block, superseded ones included."""
        return [copy.deepcopy(b) for b in sorted((b for b in self.blocks.values() if b.matchId == match_id),
                                                 key=lambda b: (b.coversFrom, b.level))]

    async def delete_match(self, match_id):
        """Remove one match's documents in every container (tombstones stay)."""
        counts = {"checkpoints": int(self.checkpoints.pop(match_id, None) is not None),
                  "contextBlocks": sum(b.matchId == match_id for b in self.blocks.values()),
                  "narratives": sum(n.matchId == match_id for n in self.items.values()),
                  "analyses": sum(d["matchId"] == match_id for d in self.analysis_docs.values()),
                  "storylines": sum(d["matchId"] == match_id for d in self.storyline_docs.values()),
                  "subscriptionDecisions": sum(d["matchId"] == match_id for d in self.decision_docs.values()),
                  "subscriptionNarratives": sum(n.matchId == match_id for n in self.follow_items.values())}
        self.blocks = {k: b for k, b in self.blocks.items() if b.matchId != match_id}
        self.items = {k: n for k, n in self.items.items() if n.matchId != match_id}
        self.analysis_docs = {k: d for k, d in self.analysis_docs.items() if d["matchId"] != match_id}
        self.storyline_docs = {k: d for k, d in self.storyline_docs.items() if d["matchId"] != match_id}
        self.decision_docs = {k: d for k, d in self.decision_docs.items() if d["matchId"] != match_id}
        self.follow_items = {k: n for k, n in self.follow_items.items() if n.matchId != match_id}
        return counts

    async def put_decision(self, decision):
        self.decision_docs.setdefault(decision["id"], copy.deepcopy(decision))

    async def get_decision(self, match_id, decision_id):
        doc = self.decision_docs.get(decision_id)
        return copy.deepcopy(doc) if doc and doc["matchId"] == match_id else None

    async def decisions(self, match_id):
        found = [d for d in self.decision_docs.values() if d["matchId"] == match_id]
        return copy.deepcopy(sorted(found, key=lambda d: (d["horizon"], d["id"])))

    async def add_subscription_narrative(self, narrative):
        self.follow_items[narrative.id] = copy.deepcopy(narrative)

    def _follows(self, match_id, topic_id=None, user_type=None):
        return [n for n in self.follow_items.values() if n.matchId == match_id
                and (topic_id is None or n.topicId == topic_id) and (user_type is None or n.userType == user_type)]

    async def subscription_narratives(self, match_id, topic_id=None, user_type=None):
        return copy.deepcopy(sorted(self._follows(match_id, topic_id, user_type),
                                    key=lambda n: (n.createdAt, n.topicId, n.userType, n.seq)))

    async def subscription_narratives_after(self, match_id, topic_id, user_type, after_seq, limit):
        found = sorted((n for n in self._follows(match_id, topic_id, user_type) if n.seq > after_seq), key=lambda n: n.seq)
        return copy.deepcopy(found[:limit])

    async def subscription_narrative_for_step(self, match_id, topic_id, user_type, step_id):
        return next((copy.deepcopy(n) for n in self._follows(match_id, topic_id, user_type) if n.stepId == step_id),
                    None)

    async def put_analysis(self, analysis):
        self.analysis_docs.setdefault(analysis["id"], copy.deepcopy(analysis))

    async def get_analysis(self, match_id, analysis_id):
        doc = self.analysis_docs.get(analysis_id)
        return copy.deepcopy(doc) if doc and doc["matchId"] == match_id else None

    async def analyses(self, match_id):
        found = [d for d in self.analysis_docs.values() if d["matchId"] == match_id]
        return copy.deepcopy(sorted(found, key=lambda d: d["horizon"]))

    async def put_storylines(self, match_id, storylines):
        for line in storylines:
            self.storyline_docs[line["id"]] = copy.deepcopy(line)

    async def storylines(self, match_id):
        found = [d for d in self.storyline_docs.values() if d["matchId"] == match_id]
        return copy.deepcopy(sorted(found, key=lambda d: d["n"]))

    async def match_ids(self):
        return sorted(self.checkpoints)

    async def add_tombstones(self, match_ids, cutoff=None):
        self.purged.update(match_ids)
        if cutoff and (self.cutoff is None or cutoff > self.cutoff):
            self.cutoff = cutoff

    async def tombstones(self):
        return set(self.purged), self.cutoff

    async def add_narrative(self, narrative):
        self.items[narrative.id] = copy.deepcopy(narrative)

    async def narratives(self, match_id, user_type=None):
        found = [n for n in self.items.values()
                 if n.matchId == match_id and (user_type is None or n.userType == user_type)]
        return sorted(found, key=lambda n: (n.createdAt, n.userType, n.seq))

    async def live_match_ids(self):
        return sorted(m for m, cp in self.checkpoints.items() if cp["status"] == "live" or cp.get("pending"))

    async def narratives_after(self, match_id, user_type, after_seq, limit):
        found = sorted((n for n in self.items.values()
                        if n.matchId == match_id and n.userType == user_type and n.seq > after_seq),
                       key=lambda n: n.seq)
        return [copy.deepcopy(n) for n in found[:limit]]

    async def narrative_for_step(self, match_id, user_type, step_id):
        return next((n for n in self.items.values()
                     if n.matchId == match_id and n.userType == user_type and n.stepId == step_id), None)
