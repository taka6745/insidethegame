"""HTTP boundaries. No user database access and no model calls."""
from urllib.parse import quote

import httpx

from ..models.snapshots import SnapshotInput


class EtlSnapshots:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')

    async def read(self, snapshot_id):
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f'{self.base_url}/demo/snapshots/{quote(snapshot_id, safe="")}')
            response.raise_for_status()
            return SnapshotInput.model_validate(response.json())


class AudienceCatalog:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')

    async def read(self, match_id):
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f'{self.base_url}/matches/{quote(match_id, safe="")}/audience-config')
            response.raise_for_status()
            body = response.json()
        if body.get('match_id') != match_id or not isinstance(body.get('generation_targets'), list):
            raise ValueError('Audience catalogue belongs to another match or is incomplete')
        return body
