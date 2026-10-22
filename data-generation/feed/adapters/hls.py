"""A run's live HLS playlist: packaged segments are copied in only once they have played.

The served directory never holds footage past the run's clock. The playlist is written only
once it lists a segment, so it does not exist (404) before the first segment or after a purge.
Directories are on disk (LocalDir, LocalLive) or in Blob Storage (adapters/blob.py).
"""
import os
import shutil
from pathlib import Path

LIVE = "live.m3u8"


def parse_segments(text):
    """[(uri, start, duration)] from a packaged VOD media playlist."""
    segments, start, duration = [], 0.0, None
    for line in text.splitlines():
        if line.startswith("#EXTINF:"):
            duration = float(line[8:].split(",")[0])
        elif line and not line.startswith("#") and duration is not None:
            if "/" in line or "\\" in line or line.startswith("."):
                raise ValueError(f"Segment URI must be a plain file name: {line!r}")
            segments.append((line, start, duration))
            start += duration
            duration = None
    return segments


def remove_dir(path):
    """Delete a run's playlist and segments. Returns the number of files removed."""
    path = Path(path)
    count = sum(1 for p in path.iterdir() if p.is_file()) if path.is_dir() else 0
    shutil.rmtree(path, ignore_errors=True)
    return count


class LocalDir:
    """One HLS directory on disk."""

    def __init__(self, path):
        self.path = Path(path)

    def read_text(self, name):
        return (self.path / name).read_text()

    def exists(self, name):
        return (self.path / name).exists()

    def copy_from(self, source, name):
        self.path.mkdir(parents=True, exist_ok=True)
        temporary = self.path / (name + ".tmp")
        try:
            os.link(source.path / name, temporary)
        except OSError:
            shutil.copyfile(source.path / name, temporary)
        temporary.replace(self.path / name)  # Whole files only.

    def write_text(self, name, text):
        self.path.mkdir(parents=True, exist_ok=True)
        temporary = self.path / (name + ".tmp")
        temporary.write_text(text)
        temporary.replace(self.path / name)  # Atomic: players never read half a playlist.

    def remove(self):
        return remove_dir(self.path)


class LocalLive:
    """Played HLS per match on disk (FEED_LIVE_DIR)."""

    def __init__(self, root):
        self.root = Path(root)

    def dir(self, match_id):
        return LocalDir(self.root / match_id)

    def match_ids(self):
        return {p.name for p in self.root.iterdir() if p.is_dir()} if self.root.is_dir() else set()

    def remove(self, match_id):
        return remove_dir(self.root / match_id)

    def open(self, match_id, name):
        """The published file's path, or None."""
        path = self.root / match_id / name
        return path if path.is_file() else None


def live_store(live):
    return LocalLive(live) if isinstance(live, (str, os.PathLike)) else live


def _dir(directory):
    return LocalDir(directory) if isinstance(directory, (str, os.PathLike)) else directory


class LivePlaylist:
    def __init__(self, source, target):
        self.source, self.target = _dir(source), _dir(target)
        self.segments = parse_segments(self.source.read_text("match.m3u8"))
        self.published = 0

    @property
    def complete(self):
        return self.published == len(self.segments)

    def next_end(self):
        """Video time at which the next segment becomes publishable, or None."""
        if self.complete:
            return None
        _, start, duration = self.segments[self.published]
        return start + duration

    def resume(self):
        """After a restart keep the published prefix; anything inconsistent starts over."""
        try:
            listed = parse_segments(self.target.read_text(LIVE))
        except (OSError, ValueError):
            listed = []
        if listed and listed == self.segments[:len(listed)] and all(self.target.exists(u) for u, _, _ in listed):
            self.published = len(listed)
        else:
            self.remove()

    def publish(self, video_seconds):
        """Publish every segment that has fully played. Returns True when the playlist changed."""
        ready = sum(1 for _, start, duration in self.segments if start + duration <= video_seconds + 1e-6)
        if ready <= self.published:
            return False
        for uri, _, _ in self.segments[self.published:ready]:
            self.target.copy_from(self.source, uri)
        self.published = ready
        self._write()
        return True

    def remove(self):
        self.published = 0
        return self.target.remove()

    def _write(self):
        target = max((d for _, _, d in self.segments), default=2.0)
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:EVENT",
                 f"#EXT-X-TARGETDURATION:{int(target + 0.999)}", "#EXT-X-MEDIA-SEQUENCE:0"]
        for uri, _, duration in self.segments[:self.published]:
            lines += [f"#EXTINF:{duration:.3f},", uri]
        if self.complete:
            lines.append("#EXT-X-ENDLIST")
        self.target.write_text(LIVE, "\n".join(lines) + "\n")
