"""One fixture's provider stream, independent of any run: what is sent, in send order, at which
video time. A run stamps its matchId and wall-clock times onto these (services/render.py)."""
from dataclasses import dataclass, field
from pathlib import Path

MA1_LEAD_SECONDS = 60.0  # MA1 goes out this long before kickoff.


@dataclass(frozen=True)
class Item:
    at: float   # Video seconds after kickoff when the item may be sent.
    kind: str   # "event" (MatchEvent v2), "MA3" or "POS".
    index: int  # Into FixtureStream.events / ma3 / pos.


@dataclass
class FixtureStream:
    fixture: str
    ma1: dict                 # Template; the run adds matchId, runId, kickoff and video.
    events: list[dict]        # Canonical MatchEvent v2 `event` bodies; seq = index + 1.
    ma3: list[dict]           # MA3 rows with nominal timeStamps; the run reschedules them.
    pos: list[dict]           # POS samples.
    items: list[Item]         # Send order after MA1.
    duration_seconds: float
    catalogue: dict           # GET /recordings entry (without media).
    sha256: str
    media: Path | None = field(default=None)  # Packaged HLS directory (match.m3u8 + segments).

    def video_at(self, period, minute):
        """Video second of the first event at or after this match-clock point; None if never reached."""
        return next((e["video_seconds"] for e in self.events
                     if e["period"] == period and e["match_time_seconds"] >= minute * 60), None)

    def entry(self):
        return {**self.catalogue, "capabilities": {**self.catalogue["capabilities"], "video": self.media is not None}}
