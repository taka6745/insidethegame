"""Blob Storage HLS against Azurite or Azure: set FEED_TEST_BLOB_CONNECTION_STRING (a throwaway account)."""
import dataclasses
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import httpx

from feed.adapters.hls import LIVE, LivePlaylist
from feed.tests.support import riverton, media

CONNECTION = os.environ.get("FEED_TEST_BLOB_CONNECTION_STRING")


class RemoveTests(unittest.TestCase):
    def test_remove_deletes_concurrently(self):
        import threading
        from types import SimpleNamespace
        from feed.adapters.blob import BlobDir

        class Container:
            deleted, threads = [], set()

            def list_blobs(self, name_starts_with):
                return [SimpleNamespace(name=f"{name_starts_with}{i:05}.ts") for i in range(300)]

            def delete_blob(self, name):
                time.sleep(0.001)
                self.threads.add(threading.get_ident())
                self.deleted.append(name)

        self.assertEqual(BlobDir(Container(), "m").remove(), 300)
        self.assertEqual(len(set(Container.deleted)), 300)
        self.assertGreater(len(Container.threads), 1)

    def test_remove_skips_blobs_already_gone(self):
        from types import SimpleNamespace
        from azure.core.exceptions import ResourceNotFoundError
        from feed.adapters.blob import BlobDir

        class Container:
            def list_blobs(self, name_starts_with):
                return [SimpleNamespace(name=f"{name_starts_with}{i}.ts") for i in range(3)]

            def delete_blob(self, name):
                if name.endswith("1.ts"):
                    raise ResourceNotFoundError("gone")

        self.assertEqual(BlobDir(Container(), "m").remove(), 3)


@unittest.skipUnless(CONNECTION, "FEED_TEST_BLOB_CONNECTION_STRING not set")
class BlobTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from feed.adapters.blob import BlobStorage
        self.storage = BlobStorage(CONNECTION)
        for name in ("recordings", "media", "live"):
            if not self.storage.service.get_container_client(name).exists():
                self.storage.service.create_container(name)
        self.fixture = f"test-{uuid.uuid4().hex[:8]}"
        source = media(Path(tempfile.mkdtemp()) / "hls", segments=4)
        self.media = self.storage.service.get_container_client("media")
        for path in source.iterdir():
            self.media.upload_blob(f"{self.fixture}/hls/{path.name}", path.read_bytes())
        self.match_id = f"{self.fixture}-abcdef12"

    def tearDown(self):
        for blob in self.media.list_blobs(name_starts_with=self.fixture + "/"):
            self.media.delete_blob(blob.name)
        self.storage.live().remove(self.match_id)

    def test_remove_purges_every_blob_and_is_idempotent(self):
        live = self.storage.live()
        container = self.storage.service.get_container_client("live")
        for i in range(40):
            container.upload_blob(f"{self.match_id}/s{i:03}.ts", b"x")
        self.assertEqual(live.remove(self.match_id), 40)
        self.assertEqual(live.remove(self.match_id), 0)
        self.assertNotIn(self.match_id, live.match_ids())

    def test_a_purge_reuses_pooled_connections(self):
        container = self.storage.service.get_container_client("live")
        for i in range(200):
            container.upload_blob(f"{self.match_id}/s{i:03}.ts", b"x")
        with self.assertNoLogs("urllib3.connectionpool", "WARNING"):  # "Connection pool is full"
            self.assertEqual(self.storage.live().remove(self.match_id), 200)

    def test_segments_are_published_only_once_played_and_purged(self):
        stream = dataclasses.replace(riverton(), fixture=self.fixture)  # riverton() is shared
        self.storage.attach_media({self.fixture: stream})
        live = self.storage.live()
        playlist = LivePlaylist(stream.media, live.dir(self.match_id))
        self.assertIsNone(live.open(self.match_id, LIVE))
        self.assertFalse(playlist.publish(1.9))
        self.assertTrue(playlist.publish(4.0))
        self.assertIsNotNone(live.open(self.match_id, "00001.ts"))
        self.assertIsNone(live.open(self.match_id, "00002.ts"))  # not played yet
        self.assertEqual(b"".join(live.open(self.match_id, "00000.ts")), b"segment 0")
        self.assertIn(self.match_id, live.match_ids())

        resumed = LivePlaylist(stream.media, live.dir(self.match_id))
        resumed.resume()
        self.assertEqual(resumed.published, 2)
        resumed.publish(8.0)
        self.assertIn("#EXT-X-ENDLIST", b"".join(live.open(self.match_id, LIVE)).decode())
        self.assertEqual(live.remove(self.match_id), 5)
        self.assertIsNone(live.open(self.match_id, LIVE))

    async def test_route_streams_published_blobs(self):
        from feed.routes.http import create_app

        class Service:
            ready = True
            seeds = False
        stream = dataclasses.replace(riverton(), fixture=self.fixture)  # riverton() is shared
        self.storage.attach_media({self.fixture: stream})
        live = self.storage.live()
        LivePlaylist(stream.media, live.dir(self.match_id)).publish(2.0)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(create_app(Service(), live)),
                                     base_url="http://feed") as client:
            playlist = await client.get(f"/hls/{self.match_id}/{LIVE}")
            self.assertEqual((playlist.status_code, playlist.headers["cache-control"]), (200, "no-cache"))
            self.assertIn("00000.ts", playlist.text)
            segment = await client.get(f"/hls/{self.match_id}/00000.ts")
            self.assertEqual((segment.status_code, segment.content), (200, b"segment 0"))
            self.assertEqual((await client.get(f"/hls/{self.match_id}/00001.ts")).status_code, 404)
