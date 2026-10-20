"""Explicit development double for replay requests. Recognises documented phrasings only."""
import re

from backend.services.replay_clips import MAX_CLIPS, MAX_ITEMS

from .replay import ReplayDecision

PERIODS = {"first": 1, "second": 2}
REPLAY_WORDS = ("show", "watch", "replay", "highlight", "clip", "how did the", "what happened")
# Ordered: the first matching phrase decides the request.
KINDS = [
    (("on goal", "on target"), "Shots on target", [{"event_types": ["goal"]}, {"event_types": ["shot"], "outcome": "saved"}]),
    (("yellow card",), "Yellow cards", [{"event_types": ["card"], "outcome": "yellow"},
                                        {"event_types": ["card"], "outcome": "second_yellow"}]),
    (("card",), "Cards", [{"event_types": ["card"]}]),
    (("intercept",), "Interceptions", [{"event_types": ["interception"]}]),
    (("header",), "Headers", [{"event_types": ["pass", "shot", "goal", "clearance"], "qualifiers": {"bodyPart": "head"}}]),
    (("goal",), "Goals", [{"event_types": ["goal"]}]),
    (("shot", "attempt"), "Shots", [{"event_types": ["shot", "goal"]}]),
    (("save",), "Saves", [{"event_types": ["save"], "qualifiers": {"defensiveBlock": False}}]),
    (("tackle",), "Tackles", [{"event_types": ["tackle"]}]),
    (("corner",), "Corners", [{"event_types": ["corner"]}]),
    (("pass",), "Passes", [{"event_types": ["pass"]}]),
]


def is_replay(prompt):
    text = prompt.lower()
    return any(word in text for word in REPLAY_WORDS)


def item(row, label):
    who = row["player"] or row["team"]
    return {"source_id": row["id"], "kind": "event", "caption": f"{row['minute']} {who} {label}"[:120],
            "lead_in": "move" if row["type"] == "goal" else "normal"}


class FixtureReplayAgent:
    mode = "fixture"

    async def plan(self, prompt, context, tools):
        text = prompt.lower().strip().rstrip("?")
        half = re.search(r"(first|second) half", text)
        period = PERIODS[half.group(1)] if half else None
        if text.startswith("how did the") and period:
            return await self.summary(tools, period)
        if "highlight" in text:
            return await self.summary(tools, None)
        recent = re.search(r"last (\d+) minutes", text)
        if recent:
            return await self.recent(tools, int(recent.group(1)))
        player = None
        if " by " in text or "'s " in text:
            wanted = (text.split(" by ", 1)[1] if " by " in text else text.split("'s ", 1)[0].split()[-1]).strip()
            player = next((p for p in context["players"] if wanted and wanted in p["name"].lower()), None)
            if not player:
                return ReplayDecision(status="answer", text=f"{wanted.title()} is not in this match. "
                                      "I can show the same moments for everyone instead.")
        for words, label, filters in KINDS:
            if any(word in text for word in words):
                return await self.find(tools, label, filters, period, player)
        return ReplayDecision(status="unsupported", text="Sorry, fixture mode recognises only listed replay requests.")

    async def find(self, tools, label, filters, period, player):
        rows, total = [], 0
        for spec in filters:
            spec = {**spec, **({"period": period} if period else {}), **({"player_id": player["id"]} if player else {})}
            found = await tools.find_events(**spec)
            if found.get("unavailable"):
                return ReplayDecision(status="answer", text=found["message"])
            rows += found["listed"]
            total += found["total"]
        rows.sort(key=lambda row: tools.events[row["id"]]["video_seconds"] or 0.0)  # Untimed recordings keep order.
        subject = f"{label} by {player['name']}" if player else label
        if not total:
            return ReplayDecision(status="answer", text=f"No {subject.lower()} so far.")
        if total > MAX_ITEMS:  # Too many to watch: a one-page sample and a way to narrow it.
            return ReplayDecision(status="answer", text=f"{subject}: {total} so far. Here is a sample.",
                                  refine_offer="Narrow it to one team, one half or one player.",
                                  items=[item(row, row["type"].replace("_", " ")) for row in rows[:MAX_CLIPS]])
        return ReplayDecision(status="answer", text=f"{subject}: {total} so far.",
                              items=[item(row, row["type"].replace("_", " ")) for row in rows])

    async def summary(self, tools, period):
        moments = sorted((await tools.key_moments(period))["items"], key=lambda m: m["rank"])
        if period:
            recaps = await tools.recaps("half", period)
            text = recaps["items"][0]["summary"] if recaps["items"] else "That half is still in progress."
        else:
            top = "; ".join(m["title"] for m in moments[:3])
            text = f"{len(moments)} key moments so far, led by {top}." if moments else "No key moments yet."
        return ReplayDecision(status="answer", text=text[:1200], items=[
            {"source_id": m["id"], "kind": "key_moment", "caption": m["title"][:120], "lead_in": "normal"}
            for m in moments])

    async def recent(self, tools, minutes):
        history = await tools.load()
        latest = history[-1]["video_seconds"] if history else 0.0
        kinds = ["goal", "shot", "card", "save", "corner", "free_kick", "offside"]
        found = [r for r in history if r["event_type"] in kinds and r["video_seconds"] >= latest - minutes * 60]
        listed = tools.listed(found)
        if not listed["total"]:
            return ReplayDecision(status="answer", text=f"Nothing notable in the last {minutes} minutes.")
        return ReplayDecision(status="answer", text=f"{listed['total']} notable moments in the last {minutes} minutes.",
                              items=[item(row, row["type"].replace("_", " ")) for row in listed["listed"][:MAX_ITEMS]])
