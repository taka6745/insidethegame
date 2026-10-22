"""Composition root. Run: uvicorn feed.app:from_env --factory (from data-generation/)."""
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from feed.adapters.eventhubs import EventHubsSink
from feed.adapters.recordings import discover
from feed.repositories.feed_db import FeedRepository
from feed.routes.http import create_app
from feed.services.clock import SystemClock
from feed.services.feed import FeedService
from feed.services.run import SendPolicy


def from_env():
    logging.basicConfig(level=logging.INFO)
    if os.environ.get("FEED_BLOB_CONNECTION_STRING"):  # Azure: recordings, media and played HLS in Blob Storage
        from feed.adapters.blob import BlobStorage
        logging.getLogger("azure").setLevel(logging.WARNING)  # the SDK logs every request at INFO
        storage = BlobStorage(os.environ["FEED_BLOB_CONNECTION_STRING"])
        streams = storage.attach_media(discover(storage.download_recordings(tempfile.mkdtemp())))
        live_root = storage.live()
    else:
        live_root = Path(os.environ.get("FEED_LIVE_DIR", "/live-media"))
        streams = discover(os.environ.get("FEED_RECORDINGS_DIR", "/recordings"), os.environ.get("FEED_MEDIA_ROOT"))
    sink = EventHubsSink(os.environ["FEED_EVENTHUB_CONNECTION_STRING"],
                         os.environ.get("FEED_EVENTHUB_NAME", "match-events"))
    service = FeedService(FeedRepository(os.environ["FEED_DATABASE_URL"]), streams, sink=sink,
                          clock=SystemClock(), live_root=live_root,
                          allow_seek=os.environ.get("FEED_ALLOW_SEEK", "0") == "1",
                          policy=SendPolicy.from_env(), seeds=os.environ.get("DEMO_SEEDS") == "1")

    @asynccontextmanager
    async def lifespan(_):
        await sink.open()
        await service.start()
        try:
            yield
        finally:
            await service.close()
            await sink.close()

    return create_app(service, live_root, lifespan)
