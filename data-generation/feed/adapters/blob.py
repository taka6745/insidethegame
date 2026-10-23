"""Azure Blob Storage for the feed on Azure (FEED_BLOB_CONNECTION_STRING).

Private containers: `recordings` (*.json, downloaded at start), `media` ({fixture}/hls/match.m3u8
and segments) and `live` ({matchId}/live.m3u8 and played segments). Segments are copied server-side
once played, so footage is never downloaded by the feed and `live` never holds it early; the feed's
/hls route streams from `live`.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

PLAYLIST = ContentSettings(content_type="application/vnd.apple.mpegurl", cache_control="no-cache")
COPY_TIMEOUT = 60.0


DELETE_WORKERS = 16


class BlobDir:
    """One HLS directory: a name prefix in a container."""

    def __init__(self, container, prefix):
        self.container, self.prefix = container, prefix.strip("/") + "/"

    def _blob(self, name):
        return self.container.get_blob_client(self.prefix + name)

    def read_text(self, name):
        try:
            return self._blob(name).download_blob(encoding="utf-8").readall()
        except ResourceNotFoundError:
            raise FileNotFoundError(self.prefix + name) from None

    def exists(self, name):
        return self._blob(name).exists()

    def copy_from(self, source, name):
        """Server-side copy (same account, so the shared key authorises the source)."""
        target = self._blob(name)
        copy = target.start_copy_from_url(source._blob(name).url)
        deadline = time.monotonic() + COPY_TIMEOUT
        status = copy["copy_status"]
        while status == "pending" and time.monotonic() < deadline:
            time.sleep(0.2)
            status = target.get_blob_properties().copy.status
        if status != "success":
            raise OSError(f"Copy of {self.prefix + name} ended {status}")

    def write_text(self, name, text):
        # One Put Blob replaces the whole playlist, so players never read half of one.
        self._blob(name).upload_blob(text.encode(), overwrite=True, content_settings=PLAYLIST)

    def remove(self):
        names = [b.name for b in self.container.list_blobs(name_starts_with=self.prefix)]
        with ThreadPoolExecutor(max_workers=DELETE_WORKERS) as pool:  # one by one, a played match took over a minute
            list(pool.map(self.container.delete_blob, names))
        return len(names)


class BlobLive:
    """Played HLS per match in the `live` container."""

    def __init__(self, container):
        self.container = container

    def dir(self, match_id):
        return BlobDir(self.container, match_id)

    def match_ids(self):
        return {p.name.rstrip("/") for p in self.container.walk_blobs(delimiter="/") if p.name.endswith("/")}

    def remove(self, match_id):
        return self.dir(match_id).remove()

    def open(self, match_id, name):
        """The published blob's chunks, or None."""
        try:
            return self.container.get_blob_client(f"{match_id}/{name}").download_blob().chunks()
        except ResourceNotFoundError:
            return None


class BlobStorage:
    def __init__(self, connection_string):
        self.service = BlobServiceClient.from_connection_string(connection_string)

    def download_recordings(self, directory):
        """Copies recordings/*.json (top level) into directory; returns it."""
        directory = Path(directory)
        container = self.service.get_container_client("recordings")
        for blob in container.list_blobs():
            if blob.name.endswith(".json") and "/" not in blob.name:
                (directory / blob.name).write_bytes(container.download_blob(blob.name).readall())
        return directory

    def attach_media(self, streams):
        """Sets each stream's media to media/{fixture}/hls when its match.m3u8 exists."""
        container = self.service.get_container_client("media")
        for stream in streams.values():
            source = BlobDir(container, f"{stream.fixture}/hls")
            if source.exists("match.m3u8"):
                stream.media = source
        return streams

    def live(self):
        return BlobLive(self.service.get_container_client("live"))
