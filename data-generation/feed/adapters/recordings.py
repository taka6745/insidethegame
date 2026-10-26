"""Discovers recordings and builds each fixture's provider stream.

A recording is any `*.json` (not an `.opta-*` export) whose teams match a roster fixture; MatchEvent v2 bodies use
the contract's field names (local/README.md Contracts §2). Media is optional: `{media_root}/{fixture}/hls/match.m3u8`.
"""
import hashlib
import json
import logging
from pathlib import Path

from grf_demo.opta import export
from grf_demo.opta_stream import ma1, ma3_rows, pos_rows

from feed.models.stream import FixtureStream, Item

log = logging.getLogger(__name__)

# Qualifiers in the MatchEvent v2 contract; others stay in the provider's own feeds.
QUALIFIERS = frozenset({
    "bodyPart", "distanceMetres", "restart", "score", "relatedEventId", "sourceShotEventId",
    "endX", "endY", "angle", "longBall", "cross", "chipped", "switchOfPlay", "offsidePass",
    "situation", "assistEventId", "bigChance", "goalMouthY", "goalMouthZ", "shotOutcome", "woodwork",
    "saveType", "defensiveBlock", "penaltyAwarded", "ownGoal", "cardReason", "leadsTo", "fromShotOffTarget"})


def canonical(raw, seq):
    qualifiers = {q["type"]: q["value"] for q in raw.get("qualifiers", ())}
    return {
        "event_id": raw["eventId"], "match_id": raw["matchId"], "revision": raw.get("revision", 1),
        "event_type": raw["typeName"], "team_id": raw.get("teamId"), "player_id": raw.get("playerId"),
        "body_part": qualifiers.get("bodyPart"), "period": raw["periodId"],
        "match_time_seconds": raw["timeMin"] * 60 + raw["timeSec"], "outcome": raw.get("outcome"),
        "distance_metres": qualifiers.get("distanceMetres"), "deleted": raw.get("deleted", False),
        "sequence": seq, "video_seconds": raw["videoSeconds"], "x": raw.get("x"), "y": raw.get("y"),
        "possession_id": raw.get("possessionId"),
        "qualifiers": {k: v for k, v in qualifiers.items() if k in QUALIFIERS},
    }


def send_order(events, ma3, pos):
    """Per canonical event: its MatchEvent, then its MA3 rows. POS interleaved by video time,
    before events at the same time."""
    rows = {}
    for i, row in enumerate(ma3):
        rows.setdefault(row["eventSeq"], []).append(i)
    items, p = [], 0
    for i, event in enumerate(events):
        at = event["video_seconds"]
        while p < len(pos) and pos[p]["videoSeconds"] <= at:
            items.append(Item(pos[p]["videoSeconds"], "POS", p))
            p += 1
        items.append(Item(at, "event", i))
        items += [Item(at, "MA3", r) for r in rows.get(i + 1, ())]
    items += [Item(pos[j]["videoSeconds"], "POS", j) for j in range(p, len(pos))]
    return items


def load(path, media_root=None):
    content = Path(path).read_bytes()
    recording = json.loads(content)
    raw = recording["events"]
    samples = recording.get("possession_samples") or []
    for times in ([e.get("videoSeconds") for e in raw], [s.get("video_seconds") for s in samples]):
        if None in times or any(b < a for a, b in zip(times, times[1:])):
            raise ValueError("Recording events and possession samples need ordered video seconds")
    sha256 = hashlib.sha256(content).hexdigest()
    f24 = export(recording)
    header = ma1(recording, f24, sha256)
    events = [canonical(e, i) for i, e in enumerate(raw, 1)]
    ma3, pos = ma3_rows(recording, f24), pos_rows(recording)
    duration = float(recording.get("playback", {}).get("duration_seconds") or raw[-1]["videoSeconds"])
    fixture = header["fixture"]
    media = Path(media_root) / fixture / "hls" if media_root else None
    catalogue = {
        "fixture": fixture, "source_match_id": recording["match_id"], "description": header["description"],
        "teams": [{"id": c["id"], "name": c["name"], "position": c["position"]} for c in header["contestant"]],
        "duration_seconds": duration, "capabilities": header["capabilities"], "synthetic": True,
    }
    return FixtureStream(fixture, header, events, ma3, pos, send_order(events, ma3, pos), duration,
                         catalogue, sha256, media if media and (media / "match.m3u8").is_file() else None)


def discover(directory, media_root=None):
    """{fixture: FixtureStream} for every usable recording; others are logged and skipped."""
    found = {}
    for path in sorted(Path(directory).glob("*.json")):
        if ".opta-" in path.name:
            continue
        try:
            stream = load(path, media_root)
        except (ValueError, KeyError, StopIteration) as exc:
            log.warning("Skipping recording %s: %s", path.name, type(exc).__name__)
            continue
        if stream.fixture in found:
            log.warning("Skipping recording %s: fixture %s already loaded", path.name, stream.fixture)
            continue
        found[stream.fixture] = stream
    return found
