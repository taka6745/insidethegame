"""Explicit development double for replay requests. Recognises documented phrasings only."""
import re


from backend.agents.replay import ReplayDecision

PERIODS = {"first": 1, "second": 2}
REPLAY_WORDS = ("show", "watch", "replay", "highlight", "clip", "how did the", "what happened")
SHOTS = ["shot", "shot_penalty", "shot_freekick"]
PASSES = ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"]
GOALS = [{"action_types": SHOTS, "results": ["success"]}, {"action_types": ["bad_touch"], "results": ["owngoal"]}]
# Ordered: the first matching phrase decides the request. {"cards": colour|None} searches cards (not SPADL).
KINDS = [
    (("on goal", "on target"), "Shots on target", [{"action_types": SHOTS, "shot_outcomes": ["goal", "saved"]}]),
    (("yellow card",), "Yellow cards", [{"cards": "yellow"}]),
    (("red card",), "Red cards", [{"cards": "red"}]),
    (("card",), "Cards", [{"cards": None}]),
    (("intercept",), "Interceptions", [{"action_types": ["interception"]}]),
    (("header",), "Headers", [{"bodyparts": ["head"]}]),
    (("goal",), "Goals", GOALS),
    (("shot", "attempt"), "Shots", [{"action_types": SHOTS}]),
    (("save",), "Saves", [{"action_types": ["keeper_save"]}]),
    (("tackle",), "Tackles", [{"action_types": ["tackle"]}]),
    (("corner",), "Corners", [{"action_types": ["corner_crossed", "corner_short"]}]),
    (("pass",), "Passes", [{"action_types": PASSES}]),
]


def is_replay(prompt):
    text = prompt.lower()
    return any(word in text for word in REPLAY_WORDS)


def item(tools, row):
    """Captioned from the evidence (outcome included), as the service captions model items."""
    goal = row["type"] in SHOTS and row.get("result") == "success" or row.get("result") == "owngoal"
    return {"source_id": row["id"], "kind": "event", "caption": tools.caption(row["id"], "event"),
            "lead_in": "move" if goal else "normal"}


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
            scope = {**({"period": period} if period else {}), **({"player_id": player["id"]} if player else {})}
            found = (await tools.find_cards(spec["cards"], **scope) if "cards" in spec else
                     await tools.find_events(**spec, **scope))
            if found.get("unavailable"):
                return ReplayDecision(status="answer", text=found["message"])
            rows += found["listed"]
            total += found["total"]
        rows.sort(key=lambda row: tools.events[row["id"]]["video_seconds"] or 0.0)  # Untimed recordings keep order.
        subject = f"{label} by {player['name']}" if player else label
        if not total:
            return ReplayDecision(status="answer", text=f"No {subject.lower()} so far.")
        clips, limit = tools.config.max_clips, tools.config.max_items
        if total > limit:  # Too many to watch: a one-page sample and a way to narrow it.
            return ReplayDecision(status="answer", text=f"{subject}: {total} so far. Here is a sample.",
                                  refine_offer="Narrow it to one team, one half or one player.",
                                  items=[item(tools, row) for row in rows[:clips]])
        return ReplayDecision(status="answer", text=f"{subject}: {total} so far.",
                              items=[item(tools, row) for row in rows])

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
        listed = await tools.recent(minutes)
        if not listed["total"]:
            return ReplayDecision(status="answer", text=f"Nothing notable in the last {minutes} minutes.")
        return ReplayDecision(status="answer", text=f"{listed['total']} notable moments in the last {minutes} minutes.",
                              items=[item(tools, row) for row in listed["listed"][:tools.config.max_items]])
