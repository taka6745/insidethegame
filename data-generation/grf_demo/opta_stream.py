"""MA1/MA3 match stream for the ETL Event Hubs contract (etl/contracts/README.md).

Converts the F24-style export one row per message: MA1 (teams, lineups, provenance, capabilities,
branding) first, then one MA3 per F24 event in file order. Team set-up rows (type 34) become the MA1
lineups. MA3 keeps extra fields for consumers: videoSeconds, sourceEventId and eventSeq (canonical
event) and possessionId. pos_rows() gives the POS possession samples the feed sends live; the shipped
file holds MA1 and MA3 only. Without --out it also rewrites <recording>.opta-f24.json. Synthetic,
Opta-style; not Stats Perform data.

    python -m grf_demo.opta_stream recordings/chelsea-united-grf.json
"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .opta import KICK_OFF, export
from .roster import FIXTURES, fixture_for

POSITION_NAMES = {1: "GK", 2: "DF", 3: "MF", 4: "FW"}
PERIOD_START_MIN = {1: 0, 2: 45, 3: 90, 4: 105, 5: 120}
WINDOW_SECONDS = 60
SPADL_PASS_FAMILY = ("pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed",
                     "corner_short", "goalkick")
SPADL_SHOT_FAMILY = ("shot", "shot_penalty", "shot_freekick")


def stamp(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def boundary(t, window=WINDOW_SECONDS):
    return datetime.fromtimestamp(math.ceil(t.timestamp() / window) * window, timezone.utc)


def period_clock(row):
    return row["timeMin"] * 60 + row["timeSec"] - PERIOD_START_MIN[row["periodId"]] * 60


def camel(key):
    head, *rest = key.split("_")
    return head + "".join(part.title() for part in rest)


def capabilities(recording):
    """What the recording supports (contract keys camelCased). The feed sets video per run."""
    source = dict(recording.get("capabilities") or {})
    event_types = source.pop("supported_event_types", sorted({e["typeName"] for e in recording["events"]}))
    result = {"canonicalEvents": True, "possessionSamples": bool(recording.get("possession_samples")),
              "video": False, "periods": max((e["periodId"] for e in recording["events"]), default=2),
              "eventTypes": event_types, **{camel(k): v for k, v in source.items()}}
    if "bodyPartEventTypes" in result:
        result["bodyPartActionTypes"] = body_part_action_types(result["bodyPartEventTypes"])
    return result


def body_part_action_types(event_types):
    """The SPADL action types whose body part is certified: every MA3 pass (type 1/2) comes from a canonical
    pass, and SPADL shots include goals, so the shot family needs both shots and goals."""
    certified = set(event_types)
    return ([*SPADL_PASS_FAMILY] if "pass" in certified else []) + \
           ([*SPADL_SHOT_FAMILY] if {"shot", "goal"} <= certified else [])


def branding(team):
    primary = team["strip"]
    secondary = tuple(round(c * 0.55) for c in primary)
    return {"primaryColour": "#%02x%02x%02x" % primary, "secondaryColour": "#%02x%02x%02x" % secondary,
            "crestAssetId": team["id"]}


def ma1(recording, f24, sha256):
    players = f24["game"]["players"]
    fixture = fixture_for(recording)
    teams = fixture["teams"]
    return {
        "feed": "MA1", "schemaVersion": 1, "matchId": recording["match_id"], "synthetic": True,
        "fixture": next(name for name, f in FIXTURES.items() if f is fixture),
        "sourceMatchId": recording["match_id"],
        "description": f"{teams[0]['name']} v {teams[1]['name']} (synthetic GRF simulation)",
        "scheduledKickoff": stamp(KICK_OFF), "timeStamp": stamp(KICK_OFF - timedelta(minutes=1)),
        "provenance": "SYNTHETIC: simulated with Google Research Football (Apache-2.0), converted by "
                      "data-generation/grf_demo/opta_stream.py; Opta-style, not Stats Perform data. "
                      "Illustrative real-name lineups; not an actual match.",
        "sourceRecordingSha256": sha256,
        "capabilities": capabilities(recording),
        "branding": {team["id"]: branding(team) for team in teams},
        "contestant": [{
            "id": team["id"], "name": team["name"], "shortName": team.get("short", team["name"]), "code": team["code"],
            **({"knownNames": team["known"]} if team.get("known") else {}), "position": side,
            "lineup": [{"playerId": p["player_id"], "name": p["name"], "shirtNumber": p["shirt_number"],
                        "position": POSITION_NAMES[p["position"]], "starter": True}
                       for p in players if p["team_id"] == team["id"]],
        } for team, side in zip(teams, ("home", "away"))],
    }


def ma3_rows(recording, f24):
    canonical = {e["eventId"]: e for e in recording["events"]}
    seqs = {e["eventId"]: i for i, e in enumerate(recording["events"], 1)}
    names = {p["player_id"]: p["name"] for p in f24["game"]["players"]}
    rows = []
    for row in f24["events"]:
        if row["type_id"] == 34:
            continue
        source = canonical[row["source_event_id"]]
        located = source.get("x") is not None
        rows.append({
            "feed": "MA3", "schemaVersion": 1, "matchId": recording["match_id"], "synthetic": True,
            "seq": len(rows) + 1, "id": row["id"], "eventId": row["event_id"], "typeId": row["type_id"],
            "periodId": row["period_id"], "timeMin": row["min"], "timeSec": row["sec"],
            "contestantId": row["team_id"], "playerId": row["player_id"],
            "playerName": names.get(row["player_id"]), "outcome": row["outcome"],
            "x": row["x"] if located else None, "y": row["y"] if located else None,
            "timeStamp": None,
            "qualifier": [{"qualifierId": q["qualifier_id"], **({"value": q["value"]} if "value" in q else {})}
                          for q in row["qualifiers"]],
            "videoSeconds": source["videoSeconds"], "sourceEventId": row["source_event_id"],
            "eventSeq": seqs[row["source_event_id"]], "possessionId": source.get("possessionId"),
        })
    return rows


def pos_rows(recording):
    """POS samples, each tagged with the latest canonical seq sent before it (POS first at equal
    videoSeconds) and that event's period. timeStamp is set by the feed."""
    events, rows, seq = recording["events"], [], 0
    for i, sample in enumerate(recording.get("possession_samples") or (), 1):
        while seq < len(events) and events[seq]["videoSeconds"] < sample["video_seconds"]:
            seq += 1
        rows.append({
            "feed": "POS", "schemaVersion": 1, "matchId": recording["match_id"], "synthetic": True,
            "sampleId": i, "periodId": events[seq - 1]["periodId"] if seq else 1,
            "videoSeconds": sample["video_seconds"], "durationSeconds": sample["duration_seconds"],
            "contestantId": sample["team_id"], "eventSeq": seq, "timeStamp": None,
        })
    return rows


def schedule(rows, kick_off=KICK_OFF):
    """Nominal timeStamps: each period starts half a second after a minute boundary, so one
    60-second window holds one match minute (etl/seeder/replay.py). Publishers rebase them."""
    anchors, last = {}, kick_off
    for row in rows:
        period = row["periodId"]
        if period not in anchors:
            start = kick_off + timedelta(seconds=row["videoSeconds"])
            anchors[period] = max(boundary(start), boundary(last)) + timedelta(seconds=0.5)
        last = anchors[period] + timedelta(seconds=period_clock(row))
        row["timeStamp"] = stamp(last)
    return rows


def stream(recording, sha256):
    f24 = export(recording)
    return [ma1(recording, f24, sha256), *schedule(ma3_rows(recording, f24))]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--out", type=Path, help="default: <recording stem>.opta-stream.jsonl")
    args = parser.parse_args()
    content = args.recording.read_bytes()
    recording = json.loads(content)
    messages = stream(recording, hashlib.sha256(content).hexdigest())
    if not args.out:  # The F24 export beside it, as package.py writes it.
        f24 = args.recording.with_name(args.recording.stem + ".opta-f24.json")
        f24.write_text(json.dumps(export(recording), separators=(",", ":")))
        print(f"wrote {f24}")
    out = args.out or args.recording.with_name(args.recording.stem + ".opta-stream.jsonl")
    out.write_text("".join(json.dumps(m, ensure_ascii=False, separators=(",", ":")) + "\n" for m in messages),
                   encoding="utf-8")
    print(f"wrote {len(messages)} messages to {out}")


if __name__ == "__main__":
    main()
