"""Convert archived GRF event telemetry to the synthetic lab event envelope.

No GRF engine import or execution. Unknown semantics remain unknown.
"""
import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


def convert(path):
    events, players, counts = [], {}, Counter()
    period = 1
    with gzip.open(path, "rt") as source:
        for line in source:
            row = json.loads(line)
            kind = row["type"]
            counts[kind] += 1
            if kind == "phase_change":
                period = row["current"]
            if kind not in {"ball_touch", "pass_result", "shot", "goal"}:
                continue
            actor = row.get("player") or row.get("passer") or row.get("last_touch")
            if not actor or actor[0] not in (0, 1) or actor[1] < 0:
                continue
            team, player = f"grf-team-{actor[0]}", f"grf-{actor[0]}-{actor[1]}"
            players[player] = {"id": player, "name": f"GRF player {actor[0]}/{actor[1]}", "team_id": team}
            seconds = int(row["match_ms"] // 1000)
            qualifiers = []
            if kind == "ball_touch" and row.get("function") == "header":
                qualifiers.append({"type": "bodyPart", "value": "head"})
            outcome = None
            if kind == "pass_result":
                outcome = "success" if row["completed"] else "failure" if row["completed"] is False else None
                distance = row.get("displacement_m")
                if distance is not None and 0 <= distance <= 200:
                    qualifiers.append({"type": "distanceMetres", "value": round(distance, 3)})
            events.append({"eventId": f"grf-{row['id']}", "matchId": "grf-full-90m", "revision": 1,
                           "sequence": len(events) + 1, "typeName": {"ball_touch": "touch", "pass_result": "pass"}.get(kind, kind),
                           "teamId": team, "playerId": player, "periodId": period,
                           "timeMin": seconds // 60, "timeSec": seconds % 60,
                           "outcome": outcome, "qualifiers": qualifiers, "synthetic": True})
    return {"synthetic": True, "match_id": "grf-full-90m",
            "description": "Archived synthetic GRF simulation, converted for algorithm benchmarks; not official Opta data.",
            "provenance": {"source": "full-90m-4k/data/events.jsonl.gz",
                           "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "source_types": dict(counts), "converter": "data-generation/grf_recording.py",
                           "limitations": ["Touch, pass result, shot and goal are distinct telemetry records, not mutually exclusive football actions.",
                                           "Pass time is completion time; distance is horizontal displacement, not total flight path.",
                                           "No inferred corners, tackles, saves, card colours or body parts. Goal actor is last touch, not certified scorer.",
                                           "Period follows GRF phase changes. AI match balance is not representative of professional football."]},
            "teams": [{"id": f"grf-team-{i}", "name": f"GRF team {i}"} for i in range(2)],
            "players": list(players.values()), "events": events, "presets": []}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    recording = convert(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
            compressed.write(json.dumps(recording, separators=(",", ":")).encode())
    print(f"Saved {len(recording['events'])} deliveries; {len(recording['players'])} players to {args.output}")
