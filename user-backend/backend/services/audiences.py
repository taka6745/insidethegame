"""Expose consistent definitions and model-ready targets without calling an LLM."""
import asyncio
import hashlib
import json


class AudienceService:
    def __init__(self, repository, registry):
        self.repository, self.registry = repository, registry
        self._documents = {}  # match_id -> (revision, document, etag): polls read only the revision.

    async def ensure(self, match):
        await asyncio.to_thread(self.repository.ensure, match.match_id, match.fixture)

    async def read(self, match_id):
        """The match's catalogue; created from its fixture template on first read."""
        match = self.registry.get(match_id)
        cached = self._documents.get(match_id)
        if cached and cached[0] == await asyncio.to_thread(self.repository.revision, match_id):
            return cached[1], cached[2]
        await self.ensure(match)
        config, revision = await asyncio.to_thread(self.repository.read, match_id)
        document = {'schema_version': 1, 'match_id': match_id, 'revision': revision,
                    **config.model_dump(), 'generation_targets': config.targets()}
        digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
        self._documents[match_id] = (revision, document, '"' + digest + '"')
        return document, '"' + digest + '"'

    def forget(self, match_ids):
        for match_id in match_ids:
            self._documents.pop(match_id, None)

    async def template(self, fixture):
        row = await asyncio.to_thread(self.repository.template, fixture)
        return {**row, 'config': row['config'].model_dump()}

    async def replace_template(self, fixture, config, expected_revision):
        revision = await asyncio.to_thread(self.repository.replace_template, fixture, config, expected_revision)
        for match in self.registry.matches.values():
            match.changed.set()  # Projections re-read their catalogue (cached by revision).
        return revision

    async def templates(self):
        return await asyncio.to_thread(self.repository.templates)
