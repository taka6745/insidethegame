"""Test double of the feed's Event Hubs stream for one run of a checked-in recording (default Riverton Rovers–Forgeham United).

MA1 (with fixture, runId, capabilities, branding), then per canonical event in seq order: POS
samples up to its video time (POS first at equal times), MatchEvent v2, its MA3 rows (eventSeq).
Timestamps are kickoff + video seconds. Synthetic, derived from checked-in recordings.
"""
import json
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path

RECORDINGS = Path(__file__).resolve().parents[2] / "data-generation" / "recordings"
FIXTURES = ("riverton-forgeham", "redcastle-portalbion", "skybridge-whitmore")
KICKOFF = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
# Riverton Rovers–Forgeham United keeps the branding its tests were written against; other fixtures use their MA1's.
TEAMS = {"riverton": ("Riverton Rovers", "RVR", "#001c68", "#0743b7"), "forgeham": ("Forgeham", "FGU", "#c7142b", "#7b0015")}


def stamp(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@cache
def sources(fixture="riverton-forgeham"):
    recording = json.loads((RECORDINGS / f"{fixture}-grf.json").read_text(encoding="utf-8"))
    lines = (RECORDINGS / f"{fixture}-grf.opta-stream.jsonl").read_text(encoding="utf-8").splitlines()
    return recording, [json.loads(line) for line in lines]


def capabilities(ma1):
    """The exported MA1's capabilities; the feed adds video per run."""
    return {**ma1["capabilities"], "video": True}


def event_v2(raw, match_id):
    q = {x["type"]: x["value"] for x in raw["qualifiers"]}
    return {"event_id": raw["eventId"], "match_id": match_id, "revision": raw.get("revision", 1),
            "event_type": raw["typeName"], "team_id": raw["teamId"], "player_id": raw["playerId"],
            "body_part": q.get("bodyPart"), "period": raw["periodId"],
            "match_time_seconds": raw["timeMin"] * 60 + raw["timeSec"], "outcome": raw["outcome"],
            "distance_metres": q.get("distanceMetres"), "deleted": raw.get("deleted", False),
            "sequence": raw["sequence"], "video_seconds": raw["videoSeconds"], "x": raw["x"], "y": raw["y"],
            "possession_id": raw["possessionId"], "qualifiers": q}


def build(run="1a2b3c4d", kickoff=KICKOFF, fixture="riverton-forgeham"):
    """The run's messages in send order; matchId = {fixture}-{run}."""
    recording, opta = sources(fixture)
    match_id = f"{fixture}-{run}"
    at = lambda video: stamp(kickoff + timedelta(seconds=video))
    ma1 = {**opta[0], "matchId": match_id, "fixture": fixture, "sourceMatchId": recording["match_id"],
           "runId": f"{run}-0000-4000-8000-000000000000", "scheduledKickoff": stamp(kickoff),
           "timeStamp": stamp(kickoff - timedelta(minutes=1)), "capabilities": capabilities(opta[0])}
    if fixture == "riverton-forgeham":
        ma1["branding"] = {t: {"primaryColour": p, "secondaryColour": s, "crestAssetId": t}
                           for t, (_, _, p, s) in TEAMS.items()}
        ma1["contestant"] = [{**c, "shortName": TEAMS[c["id"]][0], "code": TEAMS[c["id"]][1]} for c in opta[0]["contestant"]]
    ma3 = {}
    seq_of = {e["eventId"]: e["sequence"] for e in recording["events"]}
    for row in opta[1:]:
        ma3.setdefault(row["sourceEventId"], []).append(row)
    samples = sorted(recording["possession_samples"], key=lambda s: s["video_seconds"])
    out, next_sample, period, last_seq = [ma1], 0, 1, 0

    def pos(upto):
        nonlocal next_sample
        while next_sample < len(samples) and (upto is None or samples[next_sample]["video_seconds"] <= upto):
            s = samples[next_sample]
            next_sample += 1
            out.append({"feed": "POS", "schemaVersion": 1, "matchId": match_id, "synthetic": True,
                        "sampleId": next_sample, "periodId": period, "videoSeconds": s["video_seconds"],
                        "durationSeconds": s["duration_seconds"], "contestantId": s["team_id"],
                        "eventSeq": last_seq, "timeStamp": at(s["video_seconds"])})

    for raw in recording["events"]:
        pos(raw["videoSeconds"])
        period, last_seq = raw["periodId"], raw["sequence"]
        out.append({"type": "MatchEvent", "version": 2, "matchId": match_id, "seq": raw["sequence"],
                    "timeStamp": at(raw["videoSeconds"]), "synthetic": True, "event": event_v2(raw, match_id)})
        for row in ma3.get(raw["eventId"], []):
            out.append({**row, "matchId": match_id, "eventSeq": seq_of[row["sourceEventId"]],
                        "timeStamp": at(row["videoSeconds"])})
    pos(None)
    return out


def interleave(*streams):
    """Several runs on one partition, merged by send time (stable within each run)."""
    tagged = [(m["timeStamp"], i, j, m) for i, stream in enumerate(streams) for j, m in enumerate(stream)]
    return [m for *_, m in sorted(tagged, key=lambda t: (t[0], t[2], t[1]))]
