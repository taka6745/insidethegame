"""Export canonical GRF events as an Opta F24-style feed (type and qualifier IDs).

IDs follow public F24 appendices as mirrored by kloppy and socceraction; this is an
Opta-style synthetic feed, not Stats Perform data.
"""

from datetime import datetime, timedelta, timezone

from .roster import NAMES, SHIRT_NUMBERS, TEAMS, player_id

TYPES = {
    "pass": 1, "take_on": 3, "foul": 4, "foul_won": 4, "out": 5, "corner_awarded": 6,
    "tackle": 7, "interception": 8, "save": 10, "keeper_claim": 11, "clearance": 12,
    "goal": 16, "card": 17, "period_end": 30, "period_start": 32, "punch": 41, "aerial": 44,
    "challenge": 45, "ball_recovery": 49, "dispossessed": 50, "error": 51, "keeper_pickup": 52,
    "offside_provoked": 55, "ball_touch": 61, "blocked_pass": 74,
}
SHOT_TYPES = {"off_target": 13, "post": 14, "saved": 15, "blocked": 15}
BODY = {"head": 15, "right_foot": 20, "left_foot": 72, "other": 21, "hand": 21}  # Unsided foot: none.
# Penalties take Q9 from the shot's situation.
RESTART = {"free_kick": 5, "corner": 6, "throw_in": 107, "goal_kick": 124, "kick_off": 279}
SITUATION = {"regular_play": 22, "fast_break": 23, "set_piece": 24, "from_corner": 25,
             "direct_free_kick": 26, "penalty": 9, "from_throw_in": 160}
FLAGS = {"longBall": 1, "cross": 2, "chipped": 155, "switchOfPlay": 196, "bigChance": 214,
         "penaltyAwarded": 9, "defensiveBlock": 94, "fromShotOffTarget": 190}
VALUES = {"endX": 140, "endY": 141, "distanceMetres": 212, "angle": 213,
          "goalMouthY": 102, "goalMouthZ": 103}
CARDS = {"yellow": 31, "second_yellow": 32, "red": 33}
SAVES = {"caught": 176, "parried": 173}
# Role order matches the scenario: GK, RM, CF, LB, CB, CB, RB, CM, CM, CM, LM; wide men play
# as forwards in a 4-3-3 (F24 positions: 1 GK, 2 DEF, 3 MID, 4 FWD; formation ID 4 = 4-3-3).
POSITIONS = (1, 4, 4, 2, 2, 2, 2, 3, 3, 3, 4)
FORMATION_433 = 4
KICK_OFF = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)


def zone(x, y):
    if y < 21.1:
        return "Right"
    if y > 78.9:
        return "Left"
    return "Back" if x < 33.3 else "Center"


def qualifiers_for(event, ids):
    kind, result = event["typeName"], []
    for item in event["qualifiers"]:
        key, value = item["type"], item["value"]
        if key == "bodyPart" and value in BODY:
            result.append((3 if kind == "pass" and value == "head" else BODY[value], None))
        elif key == "restart" and value in RESTART:
            result.append((RESTART[value], "S" if value == "kick_off" else None))
        elif key == "situation" and value in SITUATION:
            result.append((SITUATION[value], None))
        elif key in FLAGS and value:
            result.append((FLAGS[key], None))
        elif key in VALUES:
            if key in ("endX", "endY"):
                value = min(100.0, max(0.0, value))  # F24 locations stay on the pitch.
            result.append((VALUES[key], value))
        elif key == "saveType" and value in SAVES:
            result += [(SAVES[value], None), (182, None)]  # Hands.
        elif key == "relatedEventId" and value in ids:
            result.append((55, ids[value]))
        elif key == "assistEventId" and value in ids:
            result += [(29, None), (55, ids[value])]
        elif key == "leadsTo":
            result.append((170 if value == "goal" else 169, None))
    if kind == "shot" and event["outcome"] == "blocked":
        result.append((82, None))
    if kind == "card" and event["outcome"] in CARDS:
        result += [(CARDS[event["outcome"]], None), (13, None)]
    if kind == "foul":
        result.append((13, None))
    if event.get("x") is not None:
        result.append((56, zone(event["x"], event["y"])))
    return [{"qualifier_id": qid, **({"value": str(value)} if value is not None else {})}
            for qid, value in result]


def type_id(event):
    if event["typeName"] == "shot":
        return SHOT_TYPES.get(event["outcome"], 13)
    if event["typeName"] == "pass" and any(q["type"] == "offsidePass" for q in event["qualifiers"]):
        return 2
    return TYPES.get(event["typeName"])


def outcome(event):
    if event["typeName"] == "shot":
        return 1 if event["outcome"] == "saved" else 0
    return 0 if event["outcome"] == "failure" else 1


def team_setup(team):
    slots = range(len(NAMES[team]))
    joined = lambda values: ", ".join(str(value) for value in values)
    return {"type_id": 34, "period_id": 16, "min": 0, "sec": 0, "team_id": TEAMS[team]["id"],
            "outcome": 1, "x": 0.0, "y": 0.0, "qualifiers": [
                {"qualifier_id": 130, "value": str(FORMATION_433)},
                {"qualifier_id": 30, "value": joined(player_id(team, i) for i in slots)},
                {"qualifier_id": 44, "value": joined(POSITIONS)},
                {"qualifier_id": 59, "value": joined(SHIRT_NUMBERS[team])},
                {"qualifier_id": 131, "value": joined(i + 1 for i in slots)}]}


def export(recording):
    """F24-style document. Paired and per-team events keep Opta's per-team event_id counter."""
    events = recording["events"]
    counters, ids, rows = {}, {}, []
    kept = []
    for event in events:
        kind = type_id(event)
        if kind is None:
            continue  # Touches and taken restarts are qualifiers, not F24 events.
        teams = [event["teamId"]] if event["teamId"] else [team["id"] for team in TEAMS]
        for team in teams:
            counters[team] = counters.get(team, 0) + 1
            if event["teamId"]:
                ids[event["eventId"]] = counters[team]
            kept.append((event, kind, team, counters[team]))
    assists = {q["value"] for event in events for q in event["qualifiers"] if q["type"] == "assistEventId"}
    for team in (0, 1):
        rows.append({"id": len(rows) + 1, "event_id": 0, **team_setup(team)})
    for event, kind, team, event_id in kept:
        quals = qualifiers_for(event, ids)
        if event["eventId"] in assists:
            quals.append({"qualifier_id": 210})
        stamp = KICK_OFF + timedelta(seconds=event["videoSeconds"])
        rows.append({
            "id": len(rows) + 1, "event_id": event_id, "type_id": kind,
            "period_id": event["periodId"], "min": event["timeMin"], "sec": event["timeSec"],
            "team_id": team, "player_id": event["playerId"], "outcome": outcome(event),
            # F24 coordinates stay within 0-100; simulated tracking can overshoot a line slightly.
            "x": min(100.0, max(0.0, event.get("x") or 0.0)), "y": min(100.0, max(0.0, event.get("y") or 0.0)),
            "timestamp": stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "qualifiers": quals, "source_event_id": event["eventId"],
        })
    return {
        "synthetic": True,
        "description": "Opta F24-style feed generated from a GRF simulation; not Stats Perform data.",
        "game": {"id": recording["match_id"], "home_team_id": TEAMS[0]["id"], "away_team_id": TEAMS[1]["id"],
                 "kick_off": KICK_OFF.isoformat().replace("+00:00", "Z"),
                 "players": [{"player_id": player_id(team, i), "name": name, "team_id": TEAMS[team]["id"],
                              "shirt_number": SHIRT_NUMBERS[team][i], "position": POSITIONS[i]}
                             for team in (0, 1) for i, name in enumerate(NAMES[team])]},
        "events": rows,
    }
