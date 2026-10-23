"""The feed's published HLS for one match, read over HTTP like any broadcast origin.

Only played segments are listed (local/contracts/README.md §6), so the playlist's end is the
furthest point a replay may reach. Nothing is mounted or written here."""
import os

import httpx

LIVE = "live.m3u8"


class HlsMedia:
    def __init__(self, origin, public_base="/media/hls/", *, transport=None, timeout=5):
        self.origin, self.public_base = origin.rstrip("/") + "/", public_base
        self.transport, self.timeout = transport, timeout

    @classmethod
    def from_env(cls):
        origin = os.getenv("FEED_HLS_BASE")
        return cls(origin, os.getenv("PUBLIC_HLS_BASE", "/media/hls/")) if origin else None

    def stream_url(self, match_id):
        """The browser's path to the match's published playlist."""
        return stream_path(match_id, self.public_base)

    async def published_edge(self, match_id):
        """End of the published playlist in video seconds; 0 before the first segment or after a purge."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.get(f"{self.origin}{match_id}/{LIVE}")
        except httpx.HTTPError:
            return 0.0
        if response.status_code != 200:
            return 0.0
        listed = parse_segments(response.text)
        return listed[-1][1] + listed[-1][2] if listed else 0.0


def stream_path(match_id, public_base="/media/hls/"):
    return f"{public_base}{match_id}/{LIVE}"


def parse_segments(text):
    """[(uri, start, duration)] from a media playlist, from its first segment."""
    segments, start, duration = [], 0.0, None
    for line in text.splitlines():
        if line.startswith("#EXTINF:"):
            duration = float(line[8:].split(",")[0])
        elif line and not line.startswith("#") and duration is not None:
            if "/" in line or "\\" in line or line in (".", ".."):
                raise ValueError(f"Segment URI must be a plain file name: {line!r}")
            segments.append((line, start, duration))
            start += duration
            duration = None
    return segments
