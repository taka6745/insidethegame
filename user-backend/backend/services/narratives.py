"""Shared framing and routing. Model work is independent of viewer count."""
import asyncio
from uuid import uuid4

from pydantic import ValidationError

from ..adapters.llm import ModelError
from ..domain import Preferences, RuleError
from ..models.narratives import fingerprint


class NarrativeService:
    def __init__(self, repository, framer, match_id, *, batch_size=4, max_variants=12, timeout=60):
        if not 1 <= batch_size <= 12 or not 0 <= max_variants <= 48 or not 1 <= timeout <= 120:
            raise ValueError('Invalid narrative framing limits')
        self.repository, self.framer, self.match_id = repository, framer, match_id
        self.batch_size, self.max_variants, self.timeout = batch_size, max_variants, timeout

    async def initialize(self):
        await asyncio.to_thread(self.repository.initialize)

    def key(self, target):
        return fingerprint({'target': target, 'framer': self.framer.cache_version})

    async def configuration(self):
        config, revision = await asyncio.to_thread(self.repository.config)
        return {'revision': revision, 'config': config.model_dump(),
                'limits': {'max_variants': self.max_variants, 'batch_size': self.batch_size},
                'mode': self.framer.mode}

    async def configure(self, config, revision):
        if len(config.targets()) > self.max_variants:
            raise RuleError('variant_budget', 'Disable some combinations or increase NARRATIVE_MAX_VARIANTS', 422)
        return await asyncio.to_thread(self.repository.configure, config, revision)

    async def selection(self, selections):
        config, _ = await asyncio.to_thread(self.repository.config)
        bucket = next((b for b in config.buckets if b.enabled and b.selections == selections), None)
        if bucket is None:
            raise RuleError('audience_unavailable', 'Choose an enabled audience combination', 422)
        return bucket.id

    async def select_viewer(self, token, selections):
        await self.selection(selections)

        def update(state):
            state['audience'] = selections
            # Additional layers frame text; legacy stat-card presets remain team/style based.
            try:
                preferences = Preferences(team=selections.get('team', state['team']),
                                          fan_style=selections.get('fan_style', state['fan_style']))
            except ValidationError:
                return
            state.update(preferences.model_dump())

        await asyncio.to_thread(self.repository.change_viewer, token, self.match_id, update)

    async def history(self, selections):
        config, _ = await asyncio.to_thread(self.repository.config)
        bucket = next((b for b in config.buckets if b.enabled and b.selections == selections), None)
        if bucket is None:
            return {'bucket_id': None, 'status': 'unconfigured', 'narratives': []}
        target = next(t for t in config.targets() if t['bucket_id'] == bucket.id)
        rows = await asyncio.to_thread(self.repository.history, self.match_id, bucket.id, self.key(target))
        return {'bucket_id': bucket.id, 'status': 'ready', 'narratives': [
            {'id': r['source']['id'], 'revision': r['source']['revision'], 'minute': r['source']['minute'],
             'text': r['text'], 'source': r['source'], 'bucket_id': r['bucket_id'], 'mode': r['mode']}
            for r in rows]}

    async def receive(self, narrative):
        if narrative.match_id != self.match_id:
            raise RuleError('wrong_match', 'Only the configured match is supported', 422)
        config, _ = await asyncio.to_thread(self.repository.config)
        targets = config.targets()
        if len(targets) > self.max_variants:
            raise RuleError('variant_budget', 'Enabled audience combinations exceed the framing limit', 503)
        owner = uuid4()
        # Lease spans the entire bounded operation. No DB connection is held during model calls.
        duration = self.timeout * max(1, (len(targets) + self.batch_size - 1) // self.batch_size) + 30
        if not await asyncio.to_thread(self.repository.claim, narrative, owner, duration):
            raise RuleError('framing_busy', 'This narrative is already being framed; retry shortly', 503)
        try:
            current = await asyncio.to_thread(self.repository.record, narrative)
            if not current:
                return {'status': 'superseded', 'generated': 0, 'model_calls': 0}
            saved = await asyncio.to_thread(self.repository.cached, narrative)
            existing = {(r['bucket_id'], r['framing_key']) for r in saved}
            missing = [t for t in targets if (t['bucket_id'], self.key(t)) not in existing]
            calls = 0
            for offset in range(0, len(missing), self.batch_size):
                batch = missing[offset:offset + self.batch_size]
                try:
                    response = await asyncio.wait_for(self.framer.frame(narrative, batch), self.timeout)
                    expected = {t['bucket_id'] for t in batch}
                    if len(response.variants) != len(batch) or {v.bucket_id for v in response.variants} != expected:
                        raise ValueError('Missing, unexpected or duplicate audience variants')
                except (ModelError, ValidationError, ValueError, TimeoutError) as exc:
                    raise RuleError('framing_failed', 'Framing did not validate; retry the narrative delivery', 503) from exc
                keys = {t['bucket_id']: self.key(t) for t in batch}
                await asyncio.to_thread(self.repository.save, narrative, [
                    {**v.model_dump(), 'framing_key': keys[v.bucket_id], 'mode': self.framer.mode}
                    for v in response.variants])
                calls += int(self.framer.mode != 'fixture')
            return {'status': 'framed' if targets else 'paused', 'generated': len(missing),
                    'cached': len(targets) - len(missing), 'model_calls': calls, 'mode': self.framer.mode}
        finally:
            await asyncio.shield(asyncio.to_thread(self.repository.release, narrative, owner))
