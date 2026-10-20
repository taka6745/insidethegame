"""Reference implementation of the Stream Analytics outputs and the stats view.

`stream_outputs` builds the rows and notifications the cloud job should write
for a replayed match. `stats_as_of` mirrors the matchStatsAsOf SQL view. The
local loader and the end-to-end verifier both use these as the expected result.
"""
import json
import math
from decimal import ROUND_HALF_UP, Decimal
from collections import defaultdict
from datetime import datetime, timezone

from reference import opta


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def window_end(t, window):
    """Stream Analytics tumbling windows include their end time and exclude their start."""
    return datetime.fromtimestamp(math.ceil(t.timestamp() / window) * window, timezone.utc)


def stream_outputs(messages, window):
    out = {"matches": [], "rawEvents": [], "keyEvents": [], "minuteStats": [], "notifications": []}
    minutes = defaultdict(lambda: dict.fromkeys(opta.STAT_COLUMNS, 0))
    closed = {}
    for m in messages:
        if m["feed"] == "MA1":
            teams = {c["position"]: c for c in m["contestant"]}
            out["matches"].append({
                "matchId": m["matchId"], "description": m.get("description"),
                "homeContestantId": teams["home"]["id"], "homeName": teams["home"]["name"],
                "awayContestantId": teams["away"]["id"], "awayName": teams["away"]["name"],
                "scheduledKickoff": m["scheduledKickoff"], "synthetic": m["synthetic"],
                "payload": json.dumps(m, separators=(",", ":")),
            })
            continue
        t = parse_time(m["timeStamp"])
        out["rawEvents"].append({
            "matchId": m["matchId"], "id": m["id"], "seq": m["seq"], "eventId": m["eventId"], "typeId": m["typeId"],
            "periodId": m["periodId"], "timeMin": m["timeMin"], "timeSec": m["timeSec"],
            "contestantId": m["contestantId"], "playerId": m.get("playerId"), "outcome": m["outcome"],
            "x": m.get("x"), "y": m.get("y"), "eventTime": m["timeStamp"],
            "payload": json.dumps(m, separators=(",", ":")),
        })
        key = opta.key_event(m)
        if key:
            row = {
                "matchId": m["matchId"], "id": m["id"], "keyType": key[0], "detail": key[1], "typeId": m["typeId"],
                "contestantId": m["contestantId"], "playerId": m.get("playerId"), "periodId": m["periodId"],
                "timeMin": m["timeMin"], "timeSec": m["timeSec"], "eventTime": m["timeStamp"],
                "relatedEventId": int(related) if (related := opta.q_value(m, opta.Q_RELATED_EVENT)) else None,
            }
            out["keyEvents"].append(row)
            out["notifications"].append({"messageType": "KeyEventDetected", **row})
        change = opta.period_change(m)
        if change:
            out["notifications"].append({"messageType": change, "matchId": m["matchId"], "periodId": m["periodId"],
                                         "timeMin": m["timeMin"], "timeSec": m["timeSec"], "eventTime": m["timeStamp"],
                                         "typeId": m["typeId"], "contestantId": m["contestantId"]})
        end = window_end(t, window)
        stats = minutes[(m["matchId"], m["contestantId"], m["periodId"], m["timeMin"], end)]
        for column, delta in opta.stat_deltas(m).items():
            stats[column] += delta
        prev = closed.get((m["matchId"], m["periodId"], end), -1)
        closed[(m["matchId"], m["periodId"], end)] = max(prev, m["timeMin"])

    for (match_id, contestant, period, minute, end), stats in minutes.items():
        out["minuteStats"].append({"matchId": match_id, "contestantId": contestant, "periodId": period,
                                   "timeMin": minute, "windowEnd": end.isoformat(), **stats})
    for (match_id, period, end), minute in closed.items():
        out["notifications"].append({"messageType": "MinuteClosed", "matchId": match_id, "periodId": period,
                                     "timeMin": minute, "windowEnd": end.isoformat()})
    # Period events are sent once per contestant; Service Bus duplicate detection keeps one.
    seen, notifications = set(), []
    for n in out["notifications"]:
        message_id = message_id_for(n)
        if message_id not in seen:
            seen.add(message_id)
            notifications.append(n)
    out["notifications"] = notifications
    return out


# Every Service Bus notification body carries these keys (unused ones are null), as the cloud job sends them.
NOTIFICATION_KEYS = ["messageType", "messageId", "matchId", "periodId", "timeMin", "timeSec", "eventTime", "windowEnd",
                     "id", "keyType", "detail", "typeId", "contestantId", "playerId", "relatedEventId"]


def notification_body(n):
    return {k: message_id_for(n) if k == "messageId" else n.get(k) for k in NOTIFICATION_KEYS}


def message_id_for(n):
    """Service Bus MessageId; the Stream Analytics query builds the same strings."""
    kind = n["messageType"]
    if kind == "KeyEventDetected":
        return f"{n['matchId']}:key:{n['id']}"
    if kind == "MinuteClosed":
        return f"{n['matchId']}:minute:{n['periodId']}:{n['timeMin']}"
    return f"{n['matchId']}:{kind}:{n['periodId']}"


def possession_pct(own_passes, opp_passes):
    """Share of passes, rounded half up to one decimal like SQL ROUND."""
    if not own_passes + opp_passes:
        return None
    share = Decimal(100 * own_passes) / Decimal(own_passes + opp_passes)
    return float(share.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def stats_as_of(minute_rows, matches):
    """Running totals per match, contestant and match minute, as matchStatsAsOf returns them."""
    per_minute = defaultdict(lambda: dict.fromkeys(opta.STAT_COLUMNS, 0))
    teams, grid = defaultdict(set), defaultdict(set)
    for r in minute_rows:
        key = (r["matchId"], r["contestantId"], r["periodId"], r["timeMin"])
        for c in opta.STAT_COLUMNS:
            per_minute[key][c] += r[c]
        teams[r["matchId"]].add(r["contestantId"])
        grid[r["matchId"]].add((r["periodId"], r["timeMin"]))
    positions = {}
    for m in matches:
        teams[m["matchId"]] |= {m["homeContestantId"], m["awayContestantId"]}
        positions[(m["matchId"], m["homeContestantId"])] = "home"
        positions[(m["matchId"], m["awayContestantId"])] = "away"

    running = {}
    for match_id, minutes in grid.items():
        for team in teams[match_id]:
            totals = dict.fromkeys(opta.STAT_COLUMNS, 0)
            for period, minute in sorted(minutes):
                for c in opta.STAT_COLUMNS:
                    totals[c] += per_minute.get((match_id, team, period, minute), {}).get(c, 0)
                running[(match_id, team, period, minute)] = dict(totals)

    rows = []
    for (match_id, team, period, minute), own in running.items():
        opp = next((running[(match_id, o, period, minute)] for o in teams[match_id] if o != team), None)
        opp_passes = opp["passes"] if opp else 0
        rows.append({
            "matchId": match_id, "contestantId": team, "position": positions.get((match_id, team)),
            "periodId": period, "timeMin": minute, "minuteLabel": opta.minute_label(period, minute),
            **{c: own[c] for c in opta.STAT_COLUMNS if c not in ("goals", "ownGoals")},
            "goals": own["goals"] + (opp["ownGoals"] if opp else 0),
            "ownGoals": own["ownGoals"],
            "possessionPct": possession_pct(own["passes"], opp_passes),
        })
    return sorted(rows, key=lambda r: (r["matchId"], r["periodId"], r["timeMin"], r["contestantId"]))
