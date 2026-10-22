"""Reference implementation of the Stream Analytics outputs and the stats view.

`stream_outputs` builds the rows and notifications the cloud job should write
for a replayed match; `progress_marks`, `watermark` and `match_status` give the
watermark and status (local_stream computes them in Python, Azure SQL from the
job's marks). `stats_as_of` mirrors the matchStatsAsOf SQL view. The local
loader and the end-to-end verifier both use these as the expected result.
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


TABLES = ("matches", "matchTeams", "matchPlayers", "canonicalEvents", "possessionSamples",
          "rawEvents", "keyEvents", "minuteStats")


def kind(m):
    """MA1, MA3 and POS carry `feed`; canonical events are `MatchEvent` v2 without one. Else None."""
    if not isinstance(m, dict) or not m.get("matchId"):
        return None
    if m.get("feed") in ("MA1", "MA3", "POS"):
        return m["feed"]
    if "feed" not in m and m.get("type") == "MatchEvent" and m.get("version") == 2:
        return "MatchEvent"
    return None


def match_rows(m):
    """matches, matchTeams and matchPlayers rows from one MA1."""
    teams = {c["position"]: c for c in m["contestant"]}
    match = {
        "matchId": m["matchId"], "description": m.get("description"),
        "homeContestantId": teams["home"]["id"], "homeName": teams["home"]["name"],
        "awayContestantId": teams["away"]["id"], "awayName": teams["away"]["name"],
        "scheduledKickoff": m["scheduledKickoff"], "synthetic": m["synthetic"],
        "payload": json.dumps(m, separators=(",", ":")),
        "fixture": m.get("fixture"), "sourceMatchId": m.get("sourceMatchId"), "runId": m.get("runId"),
        "capabilities": json.dumps(m["capabilities"], separators=(",", ":")) if "capabilities" in m else None,
    }
    branding = m.get("branding") or {}
    team_rows = [{"matchId": m["matchId"], "contestantId": c["id"], "position": c["position"], "name": c.get("name"),
                  "shortName": c.get("shortName"), "code": c.get("code"),
                  "knownNames": json.dumps(c["knownNames"], separators=(",", ":"), ensure_ascii=False)
                  if c.get("knownNames") else None,
                  "primaryColour": branding.get(c["id"], {}).get("primaryColour"),
                  "secondaryColour": branding.get(c["id"], {}).get("secondaryColour"),
                  "crestAssetId": branding.get(c["id"], {}).get("crestAssetId")} for c in m["contestant"]]
    players = [{"matchId": m["matchId"], "playerId": p["playerId"], "contestantId": c["id"], "name": p.get("name"),
                "shirtNumber": p.get("shirtNumber"), "position": p.get("position"), "starter": p.get("starter")}
               for c in m["contestant"] for p in c.get("lineup", [])]
    return match, team_rows, players


def canonical_row(m):
    e = m["event"]
    return {"matchId": m["matchId"], "seq": m["seq"], "eventId": e["event_id"], "revision": e.get("revision", 1),
            "eventType": e["event_type"], "teamId": e.get("team_id"), "playerId": e.get("player_id"),
            "bodyPart": e.get("body_part"), "periodId": e.get("period", 1), "matchTimeSeconds": e["match_time_seconds"],
            "outcome": e.get("outcome"), "distanceMetres": e.get("distance_metres"), "deleted": e.get("deleted", False),
            "videoSeconds": e.get("video_seconds"), "x": e.get("x"), "y": e.get("y"),
            "possessionId": e.get("possession_id"),
            "qualifiers": json.dumps(e.get("qualifiers") or {}, separators=(",", ":")), "eventTime": m["timeStamp"]}


def sample_row(m):
    return {"matchId": m["matchId"], "sampleId": m["sampleId"], "periodId": m["periodId"],
            "videoSeconds": m["videoSeconds"], "durationSeconds": m["durationSeconds"],
            "contestantId": m["contestantId"], "eventSeq": m.get("eventSeq"), "eventTime": m["timeStamp"]}


def stream_outputs(messages, window):
    out = {table: [] for table in TABLES}
    out["notifications"] = []
    minutes = defaultdict(lambda: dict.fromkeys(opta.STAT_COLUMNS, 0))
    closed = {}
    for m in messages:
        feed = kind(m)
        if feed == "MA1":
            match, team_rows, players = match_rows(m)
            out["matches"].append(match)
            out["matchTeams"] += team_rows
            out["matchPlayers"] += players
            continue
        if feed == "MatchEvent":
            out["canonicalEvents"].append(canonical_row(m))
            continue
        if feed == "POS":
            out["possessionSamples"].append(sample_row(m))
            continue
        if feed != "MA3":
            continue
        t = parse_time(m["timeStamp"])
        out["rawEvents"].append({
            "matchId": m["matchId"], "id": m["id"], "seq": m["seq"], "eventId": m["eventId"], "typeId": m["typeId"],
            "periodId": m["periodId"], "timeMin": m["timeMin"], "timeSec": m["timeSec"],
            "contestantId": m["contestantId"], "playerId": m.get("playerId"), "outcome": m["outcome"],
            "x": m.get("x"), "y": m.get("y"), "eventTime": m["timeStamp"],
            "payload": json.dumps(m, separators=(",", ":")), "eventSeq": m.get("eventSeq"),
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


def progress_marks(messages, quiet=True):
    """matchProgressMarks rows the Stream Analytics job writes, in arrival order (query.asaql step 9).

    MatchEvent s marks s - 1 complete (its MA3 rows were sent before s); a POS sample marks the latest
    event complete; a final mark per match stands for the quiet spell after its last message. Each mark
    carries the highest MA3 seq and POS sampleId sent so far; `watermark` checks they are committed.
    """
    sent, marks = {}, {}
    for m in messages:
        feed = kind(m)
        if feed in (None, "MA1"):
            continue
        s = sent.setdefault(m["matchId"], {"seq": 0, "ma3Seq": 0, "sampleId": 0})
        if feed == "MatchEvent":
            if m["seq"] > 1:
                marks.setdefault((m["matchId"], m["seq"] - 1, s["ma3Seq"], s["sampleId"]), None)
            s["seq"] = max(s["seq"], m["seq"])
        elif feed == "MA3":
            s["ma3Seq"] = max(s["ma3Seq"], m["seq"])
        elif feed == "POS":
            s["sampleId"] = max(s["sampleId"], m["sampleId"])
            if s["seq"]:
                marks.setdefault((m["matchId"], s["seq"], s["ma3Seq"], s["sampleId"]), None)
    for match_id, s in sent.items() if quiet else ():
        if s["seq"]:
            marks.setdefault((match_id, s["seq"], s["ma3Seq"], s["sampleId"]), None)
    return [dict(zip(("matchId", "seq", "ma3Seq", "sampleId"), k)) for k in marks]


def watermark(marks, rows, match_id):
    """Highest marked seq whose events 1..seq, MA3 rows 1..ma3Seq and POS samples 1..sampleId are all
    committed in rows (as dbo.asaProgress checks them on Azure SQL); 0 without one."""
    def prefix(table, key):
        have, n = {r[key] for r in rows[table] if r["matchId"] == match_id}, 0
        while n + 1 in have:
            n += 1
        return n

    events, ma3, samples = prefix("canonicalEvents", "seq"), prefix("rawEvents", "seq"), prefix("possessionSamples", "sampleId")
    return max((k["seq"] for k in marks if k["matchId"] == match_id
                and k["seq"] <= events and k["ma3Seq"] <= ma3 and k["sampleId"] <= samples), default=0)


def match_status(match, events, seq):
    """scheduled (MA1 only), live, or finished once seq reaches the final period_end."""
    periods = json.loads(match.get("capabilities") or "{}").get("periods")
    final = min((e["seq"] for e in events if e["matchId"] == match["matchId"] and e["seq"] <= seq
                 and e["eventType"] == "period_end" and e["periodId"] == periods and not e["deleted"]), default=None)
    if final is not None:
        return "finished"
    return "live" if any(e["matchId"] == match["matchId"] for e in events) else "scheduled"


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
