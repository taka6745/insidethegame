"""Probe upstream `/health` endpoints for the developer screen; failures are data, not errors."""
import asyncio

import httpx


class HealthProbe:
    def __init__(self, urls, timeout=2):
        self.urls, self.timeout = dict(urls), timeout
        self.client = None  # One pooled client: /dev/ polls this, and each new client builds an SSL context.

    async def check(self):
        self.client = self.client or httpx.AsyncClient(timeout=self.timeout)
        results = await asyncio.gather(*(self._one(self.client, url) for url in self.urls.values()))
        return [{'name': name, **result} for name, result in zip(self.urls, results)]

    @staticmethod
    async def _one(client, url):
        try:
            response = await client.get(url)
            return {'status': 'ok' if response.is_success else 'unhealthy', 'http_status': response.status_code}
        except httpx.HTTPError as exc:
            return {'status': 'unavailable', 'detail': type(exc).__name__}
