"""Replay golden set, in-process: the real tools and clip builder over the recording and bound
narrative fixtures, with the fixture double or the configured model choosing evidence.

Hard failures (any one fails the run): future leakage, invented or unobserved IDs, a clip that
does not contain its event, and broken caps. Quality: precision/recall for enumerable requests,
key-moment coverage for summaries, honest refusals for absent players.
"""
import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

from backend.agents.replay_fixture import FixtureReplayAgent
from backend.services.replay import ReplayBuilder, ReplayTools
from backend.services.replay_clips import MAX_CLIPS, MAX_ITEMS, MAX_SECONDS, ReplayPlanError

ROOT = Path(__file__).resolve().parents[2]
ABSENT = re.compile(r"(\bnot|n't) (in|playing in|part of|involved in|named in) (this|the) (match|game|squad|line-?ups?)", re.I)


def etl_row(event):
    """Canonical recording event in the ETL GraphQL history shape the backend reads."""
    return {"event_id": event["eventId"], "revision": event["revision"], "event_type": event["typeName"],
            "team_id": event["teamId"], "player_id": event["playerId"], "period": event["periodId"],
            "match_time_seconds": event["timeMin"] * 60 + event["timeSec"], "outcome": event["outcome"],
            "video_seconds": event["videoSeconds"], "x": event.get("x"), "y": event.get("y"),
            "possession_id": event.get("possessionId"), "sequence": event["sequence"],
            "qualifiers": {q["type"]: q["value"] for q in event["qualifiers"]}}


class RecordingHistory:
    def __init__(self, recording, at_video):
        self.rows = [etl_row(e) for e in recording["events"] if e["videoSeconds"] <= at_video]

    async def events(self, snapshot, offset=0, limit=100, **unused):
        return {"items": self.rows[offset:offset + limit], "has_more": offset + limit < len(self.rows),
                "complete": True}


class FixtureNarratives:
    """Bound narrative fixtures released by video time, as Narrative GraphQL would."""

    def __init__(self, fixtures, at_video):
        released = lambda row: row["release"]["video_seconds"] <= at_video
        self.minutes = [m for m in fixtures["minutes"] if released(m)]
        self.tiers = [t for t in fixtures["tiers"] if released(t)]
        moments = sorted((k for k in fixtures["key_moments"] if released(k)), key=lambda k: k["rank"])
        self.moments = [{**k, "rank": i + 1} for i, k in enumerate(moments)]

    async def read(self, snapshot, operation, period=None, tier=None, **unused):
        keep = lambda row: period is None or row["period"] == period
        if operation == "key_moments":
            return {"items": [m for m in self.moments if keep(m)]}
        if operation == "minute_recaps":
            return {"items": [{**m, "summary": m["recap"]} for m in self.minutes if keep(m)][-100:]}
        return {"items": [t for t in self.tiers if keep(t) and (tier is None or t["tier"] == tier)]}


def expected_ids(tools, spec):
    specs = spec if isinstance(spec, list) else [spec]  # A list is a union, e.g. goals or saved shots.
    return [r["event_id"] for r in tools.history if any(tools.matches(r, s) for s in specs)]


def footage(tools, ids):
    return [tools.events[i]["video_seconds"] for i in ids if i in tools.events]


def near(seconds, others, gap=3.0):
    """A save and its shot, or a corner and its delivery, show the same footage: same moment."""
    return any(abs(seconds - other) <= gap for other in others)


def resolve_at(recording, at):
    """Case positions: video seconds, or 'half_time' / 'full_time' (+ offset seconds)."""
    if isinstance(at, (int, float)):
        return float(at)
    name, _, offset = at.partition("+")
    ends = [e["videoSeconds"] for e in recording["events"] if e["typeName"] == "period_end"]
    base = {"half_time": ends[0], "full_time": ends[-1]}[name]
    return base + float(offset or 0)


def score(case, decision, built, tools, at_video, released_moments):
    hard, quality = [], {}
    items = [item.model_dump() for item in decision.items]
    for clip in (built or {}).get("clips", []):
        if clip["end"] > at_video + 1e-6:
            hard.append(f"future footage: clip ends {clip['end']} after {at_video}")
        for source in clip["source_ids"]:
            event = tools.events.get(source)
            if event and not clip["start"] <= event["video_seconds"] <= clip["end"]:
                hard.append(f"clip {clip['start']}-{clip['end']} misses its event {source}")
    if built and (len(built["clips"]) > MAX_CLIPS or built["seconds"] > MAX_SECONDS + 1e-6):
        hard.append("page exceeds 12 clips or 3 minutes")
    expect = case["expect"]
    if "filters" in expect:
        wanted = footage(tools, expected_ids(tools, expect["filters"]))
        # Key moments count by the footage of their events, like plain event items.
        chosen = footage(tools, [i["source_id"] for i in items if i["kind"] == "event"] + [
            e for i in items if i["kind"] == "key_moment" for e in tools.moments.get(i["source_id"], {}).get("event_ids", [])])
        hits = sum(near(c, wanted) for c in chosen)
        quality["precision"] = hits / len(chosen) if chosen else float(not wanted)
        if expect.get("list_all", True) and len(wanted) <= MAX_ITEMS:
            quality["recall"] = sum(near(w, chosen) for w in wanted) / len(wanted) if wanted else float(not chosen)
            quality["pass"] = quality["precision"] >= 0.9 and quality["recall"] >= 0.9
        else:
            # Broad asks get at most a one-page sample and a way to narrow, not pages of clips.
            quality["refine_offer"] = bool(decision.refine_offer)
            quality["sample"] = len(chosen) <= MAX_CLIPS
            quality["pass"] = ((not chosen or quality["precision"] >= 0.9) and quality["refine_offer"]
                               and quality["sample"])
    elif "key_moments" in expect:
        rule = expect["key_moments"]
        top = [m for m in released_moments if rule.get("period") in (None, m["period"])][:rule.get("top", 5)]
        covered = {i["source_id"] for i in items} | {e for i in items if i["kind"] == "key_moment"
                                                     for e in tools.moments.get(i["source_id"], {}).get("event_ids", [])}
        hits = sum(m["id"] in covered or bool(set(m["event_ids"]) & covered) for m in top)
        quality["coverage"] = hits / len(top) if top else 1.0
        quality["pass"] = quality["coverage"] >= rule.get("min", 0.8) and len(decision.text) > 40
    elif "window_minutes" in expect:
        latest = max((r["video_seconds"] for r in tools.history), default=0.0)
        start = latest - expect["window_minutes"] * 60
        seconds = footage(tools, [i["source_id"] for i in items if i["kind"] == "event"]) + footage(
            tools, [e for i in items if i["kind"] == "key_moment" for e in tools.moments.get(i["source_id"], {}).get("event_ids", [])[-1:]])
        inside = [s for s in seconds if s >= start]
        quality["in_window"] = len(inside) / len(seconds) if seconds else 0.0
        quality["pass"] = bool(seconds) and quality["in_window"] >= 0.9
    elif "absent" in expect:
        quality["pass"] = not items and bool(ABSENT.search(decision.text))
    elif "empty" in expect:
        quality["pass"] = not items
    elif "bounded" in expect:
        # Out-of-scope asks (e.g. "the whole match"): at most one page; hard checks cover the clips.
        quality["items"] = len(items)
        quality["pass"] = len(items) <= MAX_CLIPS
    return hard, quality


async def run_case(case, agent, recording, fixtures, builder):
    at_video = resolve_at(recording, case["at"])
    match_data, narratives = RecordingHistory(recording, at_video), FixtureNarratives(fixtures, at_video)
    tools = ReplayTools(SimpleNamespace(id=f"golden-{case['id']}"), match_data, narratives,
                        recording["players"], recording["teams"])
    await tools.load()
    context = {"players": recording["players"], "teams": recording["teams"],
               "profile": case.get("profile", {"team": "neutral", "fan_style": "casual"}),
               "observed": {"video_seconds": at_video}}
    started = time.monotonic()
    result = {"id": case["id"], "prompt": case["prompt"], "at_video": at_video}
    try:
        decision = await agent.plan(case["prompt"], context, tools)
        built = None
        if decision.items:
            built = builder.build(tools, [i.model_dump() for i in decision.items])
        hard, quality = score(case, decision, built, tools, at_video, narratives.moments)
        result.update(status=decision.status, text=decision.text, items=[i.model_dump() for i in decision.items],
                      refine_offer=decision.refine_offer, clips=(built or {}).get("clips", []),
                      hard_failures=hard, quality=quality)
    except ReplayPlanError as exc:
        result.update(hard_failures=[f"invalid plan: {exc}"], quality={"pass": False})
    except Exception as exc:  # A model or tool failure is a failed case, recorded verbatim.
        result.update(hard_failures=[], quality={"pass": False}, error=f"{type(exc).__name__}: {exc}")
    result["seconds"] = round(time.monotonic() - started, 2)
    return result


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, default=ROOT / "data-generation/recordings/chelsea-united-grf.json")
    parser.add_argument("--narratives", type=Path, default=ROOT / "narrative-engine/fixtures/grf-narratives.json")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("replay_cases.json"))
    parser.add_argument("--agent", choices=("fixture", "local"), default="fixture")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    recording, fixtures = json.loads(args.recording.read_text()), json.loads(args.narratives.read_text())
    cases = [c for c in json.loads(args.cases.read_text())["cases"] if not args.case_id or c["id"] in args.case_id]
    if args.agent == "local":
        from backend.agents.replay import ReplayAgent
        agent = ReplayAgent()
    else:
        agent = FixtureReplayAgent()
    builder = ReplayBuilder()  # Cut points only; playlists need media.
    results = [await run_case(case, agent, recording, fixtures, builder) for case in cases]
    hard = sum(bool(r["hard_failures"]) for r in results)
    passed = sum(bool(r["quality"].get("pass")) and not r["hard_failures"] for r in results)
    report = {"agent": args.agent, "cases": len(results), "passed": passed, "hard_failures": hard,
              "results": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    for r in results:
        flag = "HARD" if r["hard_failures"] else ("pass" if r["quality"].get("pass") else "FAIL")
        print(f"{flag:4} {r['id']:28} {json.dumps(r['quality'])} {r.get('error', '')}")
    print(f"{passed}/{len(results)} passed, {hard} hard failures ({args.agent})")
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
