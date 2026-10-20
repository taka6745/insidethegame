"""Replay evidence tools and clip building, bounded to one observed snapshot."""

from typing import get_args

from backend.models.events import EventType
from backend.models.recording import MAX_RECORDING_EVENTS
from .replay_clips import MAX_CLIPS, ReplayPlanError, plan_clips

MAX_LISTED = 60  # Evidence rows returned to the agent per search.
MAX_SEQUENCE_SECONDS = 15
SKIP = {"touch"}
NOTABLE = {"goal", "shot", "save", "card", "corner", "foul", "offside", "penalty"}  # Contacts are evidence for other events, not clips.
EVENT_FILTERS = {"bodyPart", "situation", "shotOutcome", "cross", "longBall", "bigChance", "saveType",
                 "offsidePass", "penaltyAwarded", "restart", "defensiveBlock"}


def minute_label(row):
    minute = row["match_time_seconds"] // 60 + 1
    if row["period"] == 1 and minute > 45:
        return f"45+{minute - 45}′"
    if row["period"] == 2 and minute > 90:
        return f"90+{minute - 90}′"
    return f"{minute}′"


class ReplayTools:
    """Model-callable reads. Every returned ID becomes citable evidence for the plan."""

    def __init__(self, snapshot, match_data, narratives, players, teams):
        self.snapshot, self.match_data, self.narratives = snapshot, match_data, narratives
        self.names = {p["id"]: p["name"] for p in players}
        self.teams = {t["id"]: t["name"] for t in teams}
        self.history = None
        self.events, self.moments, self.cited = {}, {}, set()
        self.derived = None
        self.largest_total = 0  # Largest search total, so code can tell a broad request.
        self.last_found = []  # The latest search, for a plan the model failed to finish.

    async def load(self):
        """Complete observed history, latest revision of each event, in delivery order."""
        if self.history is not None:
            return self.history
        rows, offset = [], 0
        while True:
            page = await self.match_data.events(self.snapshot, offset=offset, limit=1000)
            rows += page["items"]
            offset += len(page["items"])
            if offset > MAX_RECORDING_EVENTS:
                raise ValueError("History limit exceeded")
            if not page.get("has_more") or not page["items"]:
                break
        self.history = [r for r in rows if not r.get("deleted")]
        self.events = {r["event_id"]: r for r in self.history}
        return self.history

    def compact(self, row):
        qualifiers = row.get("qualifiers") or {}
        return {"id": row["event_id"], "minute": minute_label(row), "period": row["period"],
                "type": row["event_type"], "outcome": row.get("outcome"),
                "team": self.teams.get(row.get("team_id"), row.get("team_id")),
                "player": self.names.get(row.get("player_id")),
                **{key: qualifiers[key] for key in EVENT_FILTERS if key in qualifiers}}

    def caption(self, source_id, kind):
        """Plain neutral caption from evidence, for items the model left uncaptioned."""
        if kind == "key_moment":
            return (self.moments.get(source_id) or {}).get("title", "Key moment")[:120]
        row = self.events.get(source_id)
        if row is None:
            return "Match moment"
        who = self.names.get(row.get("player_id")) or self.teams.get(row.get("team_id")) or ""
        outcome = {"success": "", "failure": "failed"}.get(row.get("outcome"), row.get("outcome") or "")
        what = " ".join(part for part in (row["event_type"], outcome) if part).replace("_", " ")
        return " ".join(part for part in (minute_label(row), who, what) if part)[:120]

    def matches(self, row, f):
        if row["event_type"] in SKIP and f.get("event_types") != ["touch"]:
            return False
        if f.get("event_types") and row["event_type"] not in f["event_types"]:
            return False
        if f.get("team_id") and row.get("team_id") != f["team_id"]:
            return False
        if f.get("player_id") and row.get("player_id") != f["player_id"]:
            return False
        if f.get("period") and row["period"] != f["period"]:
            return False
        if f.get("outcome") and row.get("outcome") != f["outcome"]:
            return False
        minute = row["match_time_seconds"] // 60
        if f.get("from_minute") is not None and minute < f["from_minute"]:
            return False
        if f.get("to_minute") is not None and minute >= f["to_minute"]:
            return False
        qualifiers = row.get("qualifiers") or {}
        # An absent flag is false, so defensiveBlock=false selects keeper saves.
        return all(qualifiers.get(key, False if value is False else None) == value
                   for key, value in (f.get("qualifiers") or {}).items())

    def check(self, f):
        unknown = set(f.get("qualifiers") or {}) - EVENT_FILTERS
        if unknown:
            return f"Unsupported qualifier filter: {sorted(unknown)}"
        if f.get("player_id") and f["player_id"] not in self.names:
            return "That player is not in this match."
        if f.get("team_id") and f["team_id"] not in self.teams:
            return "That team is not in this match."
        return None

    def listed(self, found):
        self.largest_total = max(self.largest_total, len(found))
        self.last_found = found
        for row in found[:MAX_LISTED]:
            self.cited.add(row["event_id"])
        return {"total": len(found), "listed": [self.compact(r) for r in found[:MAX_LISTED]],
                "complete_list": len(found) <= MAX_LISTED}

    async def find_events(self, **f):
        if error := self.check(f):
            return {"unavailable": True, "message": error}
        history = await self.load()
        # The feed's vocabulary, not what has happened yet: a goal is valid before the first goal.
        kinds = set(get_args(EventType))
        if unknown := sorted(set(f.get("event_types") or []) - kinds):
            return {"unavailable": True, "message": f"{unknown} are not event types in this feed.",
                    "event_types": sorted(kinds)}
        found = [r for r in history if self.matches(r, f)]
        if not found and f.get("event_types"):
            # Empty can mean a wrong outcome or qualifier: show what those types do record.
            return {**self.listed(found), "outcomes": sorted({str(r.get("outcome")) for r in history
                                                              if r["event_type"] in f["event_types"]})}
        return self.listed(found)

    async def match_state(self):
        ended = {r["period"] for r in await self.load() if r["event_type"] == "period_end"}
        return "finished" if 2 in ended else "half-time" if ended == {1} and not any(
            r["period"] == 2 for r in self.history) else "live"

    async def recent(self, minutes):
        minutes = max(1, min(int(minutes), 45))
        history = await self.load()
        latest = max((r["video_seconds"] for r in history if r.get("video_seconds") is not None), default=0.0)
        return self.listed([r for r in history if r["event_type"] in NOTABLE and r.get("video_seconds") is not None
                            and r["video_seconds"] >= latest - minutes * 60])

    async def find_sequences(self, first, then, within_seconds, then_team):
        """Derived evidence: a `then` event shortly after a `first` event, e.g. a failed pass
        followed by an opponent's touch. Returns the `then` events; the definition is recorded."""
        for f in (first, then):
            if error := self.check(f):
                return {"unavailable": True, "message": error}
        if not 0 < within_seconds <= MAX_SEQUENCE_SECONDS or then_team not in ("same", "opponent"):
            return {"unavailable": True, "message": "Sequences span at most 15 seconds; then_team is same or opponent."}
        history = await self.load()
        found, used = [], set()
        for index, row in enumerate(history):
            if not self.matches(row, first):
                continue
            for later in history[index + 1:]:
                if later["video_seconds"] - row["video_seconds"] > within_seconds:
                    break
                same = later.get("team_id") == row.get("team_id")
                if (same == (then_team == "same")) and self.matches(later, then):
                    if later["event_id"] not in used:
                        used.add(later["event_id"])
                        found.append(later)
                    break
        self.derived = {"first": first, "then": then, "within_seconds": within_seconds, "then_team": then_team}
        return {**self.listed(found), "derived": True}

    async def key_moments(self, period=None):
        page = await self.narratives.read(self.snapshot, "key_moments", period=period, limit=100)
        for row in page["items"]:
            self.moments[row["id"]] = row
            self.cited.add(row["id"])
        return {"items": [{key: row.get(key) for key in ("id", "rank", "title", "summary", "label", "period", "event_ids")}
                          for row in page["items"]]}

    async def recaps(self, tier="minute", period=None):
        operation = "minute_recaps" if tier == "minute" else "tier_recaps"
        filters = {"period": period, "limit": 100} | ({} if tier == "minute" else {"tier": tier})
        page = await self.narratives.read(self.snapshot, operation, **filters)
        return {"items": [{key: row.get(key) for key in ("id", "label", "tier", "period", "summary", "recap")
                           if row.get(key) is not None} for row in page["items"]]}


class ReplayBuilder:
    """Turns a validated plan into clips on the published match stream (already bounded to it)."""

    def __init__(self, media=None):
        self.media = media  # adapters.hls_media.HlsMedia, or None for cut points only.

    def build(self, tools, items, page=0, until=None):
        """until: the bound saved with the answer, so later pages keep the same page assignment."""
        if tools.history is None:
            raise ReplayPlanError("Replay history was not loaded")
        for item in items:
            if item["source_id"] not in tools.cited:
                raise ReplayPlanError("Replay cites evidence the tools did not return")
        history = tools.history or []
        events = {r["event_id"]: {"video_seconds": r["video_seconds"], "event_type": r["event_type"],
                                  "period": r["period"], "possession_id": r.get("possession_id")}
                  for r in history if r.get("video_seconds") is not None}
        possession_starts = {}
        for row in history:
            if row.get("possession_id") is not None and row.get("video_seconds") is not None:
                possession_starts.setdefault(row["possession_id"], row["video_seconds"])
        periods = {}
        for row in history:
            if row["event_type"] == "period_start":
                periods[row["period"]] = (row["video_seconds"], None)
            elif row["event_type"] == "period_end" and row["period"] in periods:
                periods[row["period"]] = (periods[row["period"]][0], row["video_seconds"])
        observed = max((r["video_seconds"] for r in history if r.get("video_seconds") is not None), default=0.0)
        edge = self.media.published_edge() if self.media else None
        if edge is not None:
            observed = min(observed, edge)
        if until is not None:
            observed = min(observed, until)
        clips, total, page_count = plan_clips(items, events=events, moments=tools.moments, periods=periods,
                                             observed_video=observed, possession_starts=possession_starts, page=page)
        result = {"page": page, "page_size": MAX_CLIPS, "total_items": total, "page_count": page_count, "observed_until": observed,
                  "truncated": page + 1 < page_count,
                  "clips": [{"start": round(c.start, 3), "end": round(c.end, 3), "source_ids": c.source_ids,
                             "captions": c.captions, "marks": [round(m, 3) for m in c.marks]} for c in clips],
                  "seconds": round(sum(c.seconds for c in clips), 3), "playlist": None}
        if self.media and clips:
            # One continuous, already-published stream: seeking it avoids stitched discontinuities.
            result["playlist"] = self.media.stream_url
            for clip in result["clips"]:
                clip["playlist_start"], clip["playlist_end"] = clip["start"], clip["end"]
        return result
