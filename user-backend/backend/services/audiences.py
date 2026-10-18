"""Expose consistent definitions and model-ready targets without calling an LLM."""
import asyncio
import hashlib
import json

class AudienceService:
    def __init__(self, repository, match_id):
        self.repository, self.match_id = repository, match_id

    async def initialize(self):
        await asyncio.to_thread(self.repository.initialize, self.match_id)

    async def read(self, match_id):
        config, revision = await asyncio.to_thread(self.repository.read, match_id)
        document = {'schema_version': 1, 'match_id': match_id, 'revision': revision,
                    **config.model_dump(), 'generation_targets': config.targets()}
        digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
        return document, '"' + digest + '"'

    async def replace(self, match_id, config, expected_revision):
        await asyncio.to_thread(self.repository.read, match_id)
        return await asyncio.to_thread(self.repository.replace, match_id, config, expected_revision)
