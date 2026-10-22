"""Backend tunables (card presentation, replay timing, key-moment ranks) from Postgres.

Reads re-check the revision at most every `ttl` seconds, so an edit reaches every API
process without a restart."""
import asyncio
import hashlib
import json
import time

from backend.domain import RuleError
from backend.models.config import CONFIGS


class ConfigService:
    def __init__(self, repository, *, ttl=2.0, clock=time.monotonic):
        self.repository, self.ttl, self.clock = repository, ttl, clock
        self._values, self._checked = {}, None

    async def initialize(self):
        await self._load()

    async def _load(self):
        rows = await asyncio.to_thread(self.repository.read_all)
        missing = set(CONFIGS) - set(rows)
        if missing:
            raise RuntimeError(f'Configuration rows missing: {sorted(missing)}; run the migrations')
        self._values = {name: (revision, CONFIGS[name].model_validate(document))
                        for name, (revision, document) in rows.items() if name in CONFIGS}
        self._checked = self.clock()

    async def get(self, name):
        if self._checked is None or self.clock() - self._checked >= self.ttl:
            revisions = await asyncio.to_thread(self.repository.revisions)
            if any(self._values.get(n, (None,))[0] != r for n, r in revisions.items() if n in CONFIGS):
                await self._load()
            self._checked = self.clock()
        return self._values[name][1]

    async def document(self, name):
        await self.get(name)
        revision, model = self._values[name]
        document = {'table': name, 'revision': revision, 'value': model.model_dump(mode='json')}
        return document, '"' + hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest() + '"'

    async def replace(self, name, config, expected_revision):
        try:
            model = CONFIGS[name].model_validate(config)
        except ValueError as exc:
            raise RuleError('invalid_config', str(exc).splitlines()[0][:300], 422) from None
        revision = await asyncio.to_thread(self.repository.replace, name, model.model_dump(mode='json'), expected_revision)
        self._values[name] = (revision, model)
        return {'table': name, 'revision': revision, 'value': model.model_dump(mode='json')}
