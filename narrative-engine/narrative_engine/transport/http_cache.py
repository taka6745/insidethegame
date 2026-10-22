"""GET a JSON document with ETag revalidation, at most once per `max_age` seconds."""
import logging
import time

import httpx

log = logging.getLogger(__name__)


class CachedJson:
    def __init__(self, client: httpx.AsyncClient, url, max_age=2.0, clock=time.monotonic):
        self.client, self.url, self.max_age, self.clock = client, url, max_age, clock
        self.body, self.etag, self.checked = None, None, None
        self.ok = None  # whether the last request succeeded (None before the first)

    async def get(self):
        """The current document; raises (httpx errors, bad status) only when nothing is cached."""
        if self.body is not None and self.clock() - self.checked < self.max_age:
            return self.body
        headers = {"If-None-Match": self.etag} if self.etag else {}
        try:
            response = await self.client.get(self.url, headers=headers)
            if response.status_code != 304:
                response.raise_for_status()
                self.body, self.etag = response.json(), response.headers.get("ETag")
            self.ok = True
        except (httpx.HTTPError, ValueError):
            self.ok = False
            if self.body is None:
                raise
            log.warning("%s unavailable; keeping the cached copy", self.url)
        self.checked = self.clock()
        return self.body
