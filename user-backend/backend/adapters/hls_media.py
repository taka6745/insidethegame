"""Packaged HLS media for replay playlists: segment timings and the published live edge."""
import os
from pathlib import Path

LIVE = "live.m3u8"  # The growing published playlist; replays seek it, never past its edge.


class HlsMedia:
    def __init__(self, segments, base_url="/media/hls/", published_dir=None):
        self.segments, self.base_url = segments, base_url
        self.published_dir = Path(published_dir) if published_dir else None

    @classmethod
    def from_env(cls):
        path = os.getenv("REPLAY_HLS_PLAYLIST")
        if not path or not Path(path).exists():
            return None
        return cls(parse_segments(Path(path).read_text()), os.getenv("REPLAY_HLS_BASE", "/media/hls/"),
                   os.getenv("HLS_PUBLISH_DIR"))

    @property
    def stream_url(self):
        return self.base_url + LIVE

    def published_edge(self):
        """End of the published playlist: a clip must not need a segment players cannot list yet."""
        if self.published_dir is None:
            return None
        try:
            listed = parse_segments((self.published_dir / LIVE).read_text())
        except OSError:
            return 0.0
        return listed[-1][1] + listed[-1][2] if listed else 0.0


def parse_segments(text):
    """[(uri, start, duration)] from a packaged VOD media playlist."""
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
