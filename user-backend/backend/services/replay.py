"""Replay evidence tools and clip building over SPADL actions and MA3 cards, bounded to one snapshot."""
import re
from typing import get_args

from backend.models.actions import ActionType, Bodypart, PASS_FAMILY, Result, SaveKind, SHOT_FAMILY, ShotOutcome, Zone
from backend.models.events import minute_label
from .replay_clips import ReplayPlanError, plan_clips

MAX_LISTED = 60  # Evidence rows returned to the agent per search.
MAX_SEQUENCE_SECONDS = 15
SKIP = {"dribble"}  # Carries link other actions; listed only when asked for.
# Clip-worthy for "what just happened": shots, saves, fouls, set pieces, offsides, goals and cards.
NOTABLE = {*SHOT_FAMILY, "keeper_save", "foul", "corner_crossed", "corner_short", "freekick_crossed", "freekick_short"}
FILTERS = {"action_types": ActionType, "results": Result, "bodyparts": Bodypart, "start_zones": Zone,
           "end_zones": Zone, "shot_outcomes": ShotOutcome, "save_kinds": SaveKind}
COLUMNS = {"action_types": "action_type", "results": "result", "bodyparts": "bodypart", "start_zones": "start_zone",
           "end_zones": "end_zone", "shot_outcomes": "shot_outcome", "save_kinds": "save_kind"}
SAVED = re.compile(r"\bsav(?:e|ed|es|ing)\b", re.I)
SHOT_WORDS = {"goal": "goal", "saved": "shot saved", "blocked": "shot blocked", "post": "shot hits the post",
              "off_target": "shot off target"}
SAVE_WORDS = {"save": "save", "wide_touch": "keeper touches a shot wide", "block": "blocked shot"}


def label(row):
    return minute_label(row["period"], row["match_time_seconds"])


def is_goal(row):
    return row.get("result") == "owngoal" or (row.get("action_type") in SHOT_FAMILY and row.get("result") == "success")


def timing_key(row):
    """The replay-timing key of an evidence row: goal, card or its SPADL type."""
    return "card" if "colour" in row else "goal" if is_goal(row) else row["action_type"]


def filter_text(f):
    """A search filter in words, e.g. "failed pass/cross"."""
    results = {"fail": "failed", "success": "successful"}
    parts = ["/".join(results.get(r, r) for r in f.get("results") or []),
             "/".join(f.get("action_types") or []) or "action",
             "into " + "/".join(f["end_zones"]) if f.get("end_zones") else ""]
    return " ".join(part for part in parts if part).replace("_", " ")


def false_save(row, caption):
    """A caption calling a shot that was not saved (or a goal) a save."""
    if not caption or not SAVED.search(caption) or "colour" in row:
        return False
    if row.get("action_type") in SHOT_FAMILY:
        return row.get("shot_outcome") != "saved"
    if row.get("save_kind"):
        return row["save_kind"] != "save"
    return is_goal(row)


class ReplayTools:
    """Model-callable reads. Every returned ID becomes citable evidence for the plan."""

    def __init__(self, snapshot, match_data, narratives, players, teams, config):
        self.snapshot, self.match_data, self.narratives = snapshot, match_data, narratives
        self.config = config  # models/config.Replay
        self.names = {p["id"]: p["name"] for p in players}
        self.teams = {t["id"]: t["name"] for t in teams}
        self.history = None
        self.events, self.moments, self.cited = {}, {}, set()  # events: evidence id -> action or card row
        self.cards, self.periods = [], {}
        self.derived = None
        self.largest_total = 0  # Largest search total, so code can tell a broad request.
        self.last_found = []  # The latest search, for a plan the model failed to finish.

    async def load(self):
        """Every final SPADL action at the snapshot, in action order, plus its cards and periods."""
        if self.history is not None:
            return self.history
        rows, offset = [], 0
        while True:
            page = await self.match_data.actions(self.snapshot, offset=offset, limit=1000)
            rows += page["items"]
            offset += len(page["items"])
            if not page.get("has_more") or not page["items"]:
                break
        self.cards = await self.match_data.cards(self.snapshot)
        self.periods = await self.match_data.periods(self.snapshot)
        self.history = rows
        self.events = {r["id"]: r for r in [*rows, *self.cards]}
        return self.history

    def compact(self, row):
        if "colour" in row:
            return {"id": row["id"], "minute": label(row), "period": row["period"], "type": "card",
                    "colour": row["colour"], "team": self.teams.get(row.get("team_id"), row.get("team_id")),
                    "player": self.names.get(row.get("player_id"))}
        return {"id": row["id"], "minute": label(row), "period": row["period"], "type": row["action_type"],
                "result": row["result"], "team": self.teams.get(row.get("team_id"), row.get("team_id")),
                "player": self.names.get(row.get("player_id")),
                **({"bodypart": row["bodypart"]} if row.get("bodypart_observed") else {}),
                **({"shot_outcome": row["shot_outcome"]} if row.get("shot_outcome") else {}),
                **({"save_kind": row["save_kind"]} if row.get("save_kind") else {}),
                "zones": f"{row['start_zone']}->{row['end_zone']}"}

    def caption(self, source_id, kind):
        """Plain neutral caption from evidence, for items the model left uncaptioned."""
        if kind == "key_moment":
            return (self.moments.get(source_id) or {}).get("title", "Key moment")[:120]
        row = self.events.get(source_id)
        if row is None:
            return "Match moment"
        who = self.names.get(row.get("player_id")) or self.teams.get(row.get("team_id")) or ""
        if "colour" in row:
            what = row["colour"].replace("_", " ") + " card"
        elif row.get("result") == "owngoal":
            what = "own goal"
        elif row.get("shot_outcome"):
            what = ("header " if row.get("bodypart") == "head" else "") + SHOT_WORDS[row["shot_outcome"]]
        elif row.get("save_kind"):
            what = SAVE_WORDS[row["save_kind"]]
        else:
            what = row["action_type"].replace("_", " ")
            if row.get("result") == "fail" and row["action_type"] in {*PASS_FAMILY, "take_on", "tackle"}:
                what = "failed " + what
            elif row.get("result") == "offside":
                what += " (offside)"
            if row.get("bodypart") == "head" and row.get("bodypart_observed"):
                what = "headed " + what
        return " ".join(part for part in (label(row), who, what) if part)[:120]

    def checked_caption(self, source_id, kind, caption):
        """The model's caption unless it contradicts the evidence (an unsaved shot called saved)."""
        row = self.events.get(source_id) if kind == "event" else None
        if caption and not (row and false_save(row, caption)):
            return caption
        return self.caption(source_id, kind)

    def matches(self, row, f):
        if row["action_type"] in SKIP and "dribble" not in (f.get("action_types") or []):
            return False
        for name, column in COLUMNS.items():
            if f.get(name) and row.get(column) not in f[name]:
                return False
        return self._scope(row, f)

    def _scope(self, row, f):
        if f.get("team_id") and row.get("team_id") != f["team_id"]:
            return False
        if f.get("player_id") and row.get("player_id") != f["player_id"]:
            return False
        if f.get("period") and row["period"] != f["period"]:
            return False
        minute = row["match_time_seconds"] // 60
        if f.get("from_minute") is not None and minute < f["from_minute"]:
            return False
        return f.get("to_minute") is None or minute < f["to_minute"]

    def check(self, f):
        for name, kinds in FILTERS.items():
            if unknown := sorted(set(f.get(name) or []) - set(get_args(kinds))):
                return f"{unknown} are not SPADL {name.replace('_', ' ')}: use {sorted(get_args(kinds))}."
        if f.get("player_id") and f["player_id"] not in self.names:
            return "That player is not in this match."
        if f.get("team_id") and f["team_id"] not in self.teams:
            return "That team is not in this match."
        return None

    def evidence_id(self, identifier):
        """A cited ID as the tools list it: `action:{id}` from the question context is the bare action id."""
        bare = identifier.removeprefix("action:")
        return bare if bare in self.events else identifier

    def cite_shown(self, context):
        """Actions and cards the agent's input already shows (recent tail, key events) become citable,
        when they are evidence at this snapshot."""
        compact = context.get("compact") or {}
        for row in [*compact.get("tail", []), *compact.get("key_events", [])]:
            if (identifier := self.evidence_id(str(row.get("id", "")))) in self.events:
                self.cited.add(identifier)

    def listed(self, found):
        self.largest_total = max(self.largest_total, len(found))
        self.last_found = found
        for row in found[:MAX_LISTED]:
            self.cited.add(row["id"])
        return {"total": len(found), "listed": [self.compact(r) for r in found[:MAX_LISTED]],
                "complete_list": len(found) <= MAX_LISTED}

    async def find_events(self, **f):
        if error := self.check(f):
            return {"unavailable": True, "message": error}
        history = await self.load()
        found = [r for r in history if self.matches(r, f)]
        if not found and f.get("action_types"):
            # Empty can mean a wrong result or zone: show what those types do record.
            return {**self.listed(found), "results": sorted({r["result"] for r in history
                                                             if r["action_type"] in f["action_types"]})}
        return self.listed(found)

    async def find_cards(self, colour=None, **f):
        if error := self.check(f):
            return {"unavailable": True, "message": error}
        await self.load()
        # A second yellow is both a yellow card and a sending-off.
        colours = {"red": {"red", "second_yellow"}, "yellow": {"yellow", "second_yellow"}}.get(colour, {colour} if colour else None)
        return self.listed([r for r in self.cards if (colours is None or r["colour"] in colours) and self._scope(r, f)])

    async def match_state(self):
        await self.load()
        ended = {period for period, (_, end) in self.periods.items() if end is not None}
        return "finished" if 2 in ended else "half-time" if ended == {1} and 2 not in self.periods else "live"

    async def recent(self, minutes):
        minutes = max(1, min(int(minutes), 45))
        history = await self.load()
        rows = [*history, *self.cards]
        latest = max((r["video_seconds"] for r in rows if r.get("video_seconds") is not None), default=0.0)
        notable = [r for r in rows if ("colour" in r or r["action_type"] in NOTABLE or r.get("result") == "offside"
                                       or is_goal(r)) and r.get("video_seconds") is not None
                   and r["video_seconds"] >= latest - minutes * 60]
        return self.listed(sorted(notable, key=lambda r: r["video_seconds"]))

    async def find_sequences(self, first, then, within_seconds, then_team):
        """Derived evidence: a `then` action shortly after a `first` action, e.g. a failed pass
        followed by an opponent's interception. Returns the `then` actions; the definition is recorded."""
        for f in (first, then):
            if error := self.check(f):
                return {"unavailable": True, "message": error}
        if not 0 < within_seconds <= MAX_SEQUENCE_SECONDS or then_team not in ("same", "opponent"):
            return {"unavailable": True, "message": "Sequences span at most 15 seconds; then_team is same or opponent."}
        history = [r for r in await self.load() if r.get("video_seconds") is not None]
        found, used = [], set()
        for index, row in enumerate(history):
            if not self.matches(row, first):
                continue
            for later in history[index + 1:]:
                if later["video_seconds"] - row["video_seconds"] > within_seconds:
                    break
                same = later.get("team_id") == row.get("team_id")
                if (same == (then_team == "same")) and self.matches(later, then):
                    if later["id"] not in used:
                        used.add(later["id"])
                        found.append(later)
                    break
        team = "same-team" if then_team == "same" else "opponent"
        self.derived = {"first": first, "then": then, "within_seconds": within_seconds, "then_team": then_team,
                        "description": f"{filter_text(first)}, then {team} {filter_text(then)} within {within_seconds} s"}
        return {**self.listed(found), "derived": True}

    async def key_moments(self, period=None):
        await self.load()
        page = await self.narratives.read(self.snapshot, "key_moments", period=period, limit=100)
        for row in page["items"]:
            self.moments[row["id"]] = row
            self.cited.add(row["id"])
            # Its events are returned evidence too, should the plan cite them as events.
            self.cited.update(i for i in row.get("event_ids") or [] if i in self.events)
        return {"items": [{key: row.get(key) for key in ("id", "rank", "title", "summary", "label", "period", "event_ids")}
                          for row in page["items"]]}

    async def recaps(self, tier="minute", period=None):
        operation = "minute_recaps" if tier == "minute" else "tier_recaps"
        filters = {"period": period, "limit": 100} | ({} if tier == "minute" else {"tier": tier})
        page = await self.narratives.read(self.snapshot, operation, **filters)
        return {"items": [{key: row.get(key) for key in ("id", "label", "tier", "period", "summary", "recap")
                           if row.get(key) is not None} for row in page["items"]]}


class ReplayBuilder:
    """Turns a validated plan into clips on the match's published stream (already bounded to it)."""

    def __init__(self, media=None):
        self.media = media  # adapters.hls_media.HlsMedia, or None for cut points only.

    async def edge(self, snapshot, video):
        """End of the match's published playlist (None without footage): clips never need a
        segment that players cannot list yet."""
        return await self.media.published_edge(snapshot.match_id) if self.media and video else None

    def build(self, tools, items, page=0, until=None, edge=None):
        """until: the bound saved with the answer, so later pages keep the same page assignment."""
        if tools.history is None:
            raise ReplayPlanError("Replay history was not loaded")
        for item in items:
            if item["source_id"] not in tools.cited:
                raise ReplayPlanError("Replay cites evidence the tools did not return")
        history = tools.history or []
        rows = [*history, *tools.cards]
        events = {r["id"]: {"video_seconds": r["video_seconds"], "event_type": timing_key(r),
                            "period": r["period"], "possession_id": r.get("possession_id")}
                  for r in rows if r.get("video_seconds") is not None}
        possession_starts = {}
        for row in history:
            if row.get("possession_id") is not None and row.get("video_seconds") is not None:
                possession_starts.setdefault(row["possession_id"], row["video_seconds"])
        periods = tools.periods
        observed = max((r["video_seconds"] for r in rows if r.get("video_seconds") is not None), default=0.0)
        if edge is not None:
            observed = min(observed, edge)
        if until is not None:
            observed = min(observed, until)
        clips, total, page_count = plan_clips(items, events=events, moments=tools.moments, periods=periods,
                                             observed_video=observed, possession_starts=possession_starts,
                                             page=page, config=tools.config)
        result = {"page": page, "page_size": tools.config.max_clips, "total_items": total, "page_count": page_count,
                  "observed_until": observed, "truncated": page + 1 < page_count,
                  "clips": [{"start": round(c.start, 3), "end": round(c.end, 3), "source_ids": c.source_ids,
                             "captions": c.captions, "marks": [round(m, 3) for m in c.marks]} for c in clips],
                  "seconds": round(sum(c.seconds for c in clips), 3), "playlist": None,
                  "playback": tools.config.playback.model_dump()}
        if self.media and edge is not None and clips:
            # The match's own published stream: seeking it avoids stitched discontinuities.
            result["playlist"] = self.media.stream_url(tools.snapshot.match_id)
            for clip in result["clips"]:
                clip["playlist_start"], clip["playlist_end"] = clip["start"], clip["end"]
        return result
