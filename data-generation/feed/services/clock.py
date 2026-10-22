"""Wall clock; tests substitute a fake with the same two methods."""
import asyncio
from datetime import datetime, timezone


class SystemClock:
    def now(self):
        return datetime.now(timezone.utc)

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)
