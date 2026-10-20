import copy


class MemoryStore:
    def __init__(self):
        self.checkpoints, self.blocks, self.items = {}, {}, {}

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

    async def add_narrative(self, narrative):
        self.items[narrative.id] = copy.deepcopy(narrative)

    async def narratives(self, match_id, user_type=None):
        found = [n for n in self.items.values()
                 if n.matchId == match_id and (user_type is None or n.userType == user_type)]
        return sorted(found, key=lambda n: (n.createdAt, n.userType, n.seq))

    async def live_match_ids(self):
        return sorted(m for m, cp in self.checkpoints.items() if cp["status"] == "live")

    async def narratives_after(self, match_id, user_type, after_seq, limit):
        found = sorted((n for n in self.items.values()
                        if n.matchId == match_id and n.userType == user_type and n.seq > after_seq),
                       key=lambda n: n.seq)
        return [copy.deepcopy(n) for n in found[:limit]]

    async def narrative_for_step(self, match_id, user_type, step_id):
        return next((n for n in self.items.values()
                     if n.matchId == match_id and n.userType == user_type and n.stepId == step_id), None)
