"""Local stand-in for a broadcaster's CDN origin: publishes packaged HLS segments on the replay clock.

A segment is copied to the served directory only once the shared clock has passed its end,
so footage after the live edge does not exist where viewers (or replay playlists) can reach it.
"""
import os
import shutil
import threading
from pathlib import Path

from .hls_media import LIVE, parse_segments


class HlsPublisher:
    def __init__(self, source, target):
        self.source, self.target = Path(source), Path(target)
        self.segments = parse_segments((self.source / "match.m3u8").read_text())
        self.published = 0
        self._lock = threading.Lock()  # Cancelled publish threads keep running; never interleave.

    @classmethod
    def from_env(cls):
        source, target = os.getenv("HLS_SOURCE_DIR"), os.getenv("HLS_PUBLISH_DIR")
        if not source or not target or not (Path(source) / "match.m3u8").exists():
            return None
        return cls(source, target)

    def resume(self):
        """After a restart keep the published prefix, so open players never lose footage."""
        with self._lock:
            try:
                listed = parse_segments((self.target / LIVE).read_text())
            except (OSError, ValueError):
                listed = None
            if listed is None or listed != self.segments[:len(listed)] or not all(
                    (self.target / uri).exists() for uri, _, _ in listed[-1:]):
                return self._reset()
            self.published = len(listed)

    def reset(self):
        with self._lock:
            self._reset()

    def _reset(self):
        self.target.mkdir(parents=True, exist_ok=True)
        for path in self.target.iterdir():
            if path.suffix in (".ts", ".m3u8", ".tmp"):
                path.unlink()
        self.published = 0
        self._write(finished=False)

    def publish(self, playback_seconds, *, finished=False):
        """Publish every segment that has fully elapsed; the live playlist grows in place."""
        with self._lock:
            return self._publish(playback_seconds, finished)

    def _publish(self, playback_seconds, finished):
        ready = len(self.segments) if finished else sum(
            1 for _, start, duration in self.segments if start + duration <= playback_seconds)
        if ready == self.published and not finished:
            return False
        self.target.mkdir(parents=True, exist_ok=True)
        for uri, _, _ in self.segments[ready:self.published]:  # A resumed prefix past the clock.
            (self.target / uri).unlink(missing_ok=True)
        for uri, _, _ in self.segments[self.published:ready]:
            destination = self.target / uri
            if not destination.exists():
                # Whole files only: a crash mid-copy must not leave a truncated, cached segment.
                temporary = destination.with_suffix(".tmp")
                try:
                    os.link(self.source / uri, temporary)
                except OSError:
                    shutil.copyfile(self.source / uri, temporary)
                temporary.replace(destination)
        self.published = ready
        self._write(finished)
        return True

    def _write(self, finished):
        target = max((duration for _, _, duration in self.segments), default=2.0)
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:EVENT",
                 f"#EXT-X-TARGETDURATION:{int(target + 0.999)}", "#EXT-X-MEDIA-SEQUENCE:0"]
        for uri, _, duration in self.segments[:self.published]:
            lines += [f"#EXTINF:{duration:.3f},", uri]
        if finished:
            lines.append("#EXT-X-ENDLIST")
        temporary = self.target / (LIVE + ".tmp")
        temporary.write_text("\n".join(lines) + "\n")
        temporary.replace(self.target / LIVE)  # Atomic: players never read half a playlist.
