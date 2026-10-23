"""Serve active narrative prompts to the engine; developers add or roll back versions."""
import asyncio
import hashlib
import json


class PromptService:
    def __init__(self, repository):
        self.repository = repository

    async def initialize(self):
        await asyncio.to_thread(self.repository.initialize)

    async def read(self):
        revision, rows = await asyncio.to_thread(self.repository.active)
        document = {'revision': revision, 'prompts': [dict(row) for row in rows]}
        digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
        return document, '"' + digest + '"'

    async def template(self, role):
        """The active template of one role (this service's own roles, e.g. subscription-planner)."""
        _, rows = await asyncio.to_thread(self.repository.active)
        return next(row['template'] for row in rows if row['role'] == role)

    async def versions(self):
        active, rows = await asyncio.to_thread(self.repository.versions)
        # A save must keep the active version's placeholders, read from its own row (it may be older than the list).
        roles = {role: {'role': role, 'active_version': a['version'], 'placeholders': a['placeholders'], 'versions': []}
                 for role, a in active.items()}
        for row in rows:
            roles[row.pop('role')]['versions'].append({**row, 'created_at': row['created_at'].isoformat()})
        return {'roles': sorted(roles.values(), key=lambda r: r['role'])}

    async def save(self, role, template, expected_version):
        return {'role': role, 'version': await asyncio.to_thread(self.repository.save, role, template, expected_version)}

    async def activate(self, role, version):
        return {'role': role, 'version': await asyncio.to_thread(self.repository.activate, role, version)}
