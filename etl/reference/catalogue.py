"""Python twin of dbo.statsAtSeq over the 008 seed (with 017's definition updates); tests compare them."""
import json
import re
from pathlib import Path

from reference.opta import qualifiers as _qualifiers

MIGRATION = Path(__file__).resolve().parents[1] / "sql" / "migrations" / "008_spadl_catalogue.sql"
UPDATES = MIGRATION.with_name("017_entry_definitions.sql")  # later definition texts, applied over the seed
ZONE_RANK = {"own_box": 0, "defensive_third": 1, "middle_third": 2, "final_third": 3, "opp_box": 4}
CARD, VAR, VAR_OUTCOME, OWN_GOAL = 17, 900, 901, 28


def definitions():
    """The seeded statDefinitions rows, in displayOrder."""
    seed = re.search(r"@definitions nvarchar\(max\) = N'(.*?)';", MIGRATION.read_text(encoding="utf-8"), re.S)
    rows = json.loads(seed.group(1).replace("''", "'"))
    update = re.search(r"@definitionUpdates nvarchar\(max\) = N'(.*?)';", UPDATES.read_text(encoding="utf-8"), re.S)
    texts = {u["statId"]: u["definition"] for u in json.loads(update.group(1).replace("''", "'"))}
    rows = [{**row, "definition": texts.get(row["statId"], row["definition"])} for row in rows]
    return [{**row, "displayOrder": i + 1, "enabled": True} for i, row in enumerate(rows)]


def _hit(d, a, home):
    counter = d["counter"]
    if counter in ("accuracy", "goals"):
        return a["resultName"] == "success"
    rel_end_x = a["endX"] if a["teamId"] == home else 105.0 - a["endX"]
    if counter == "on_target":
        return a["resultName"] == "success" or (a["sourceTypeId"] == 15 and rel_end_x >= 105)
    if counter == "blocked":
        return a["resultName"] != "success" and a["sourceTypeId"] == 15 and rel_end_x < 105
    if counter == "keeper_saves":
        return not a.get("fromShotOffTarget") and not a.get("defensiveBlock")
    matches = d["result"] is None or a["resultName"] == d["result"]
    if counter == "entries":
        rank = ZONE_RANK[d["zone"]]
        return matches and ZONE_RANK[a["startZone"]] < rank <= ZONE_RANK[a["endZone"]]
    return matches  # count, opponent_count


def _available(d, caps, total, possessed):
    requires = d["requires"]
    certified = set(caps.get("bodyPartActionTypes", []))
    return (d["counter"] != "retired"
            and ("shotOutcomes" not in requires or caps.get("shotOutcomes") is True)
            and ("bodyParts" not in requires or caps.get("bodyParts") is True or set(d["actionTypes"]) <= certified)
            and (d["counter"] != "accuracy" or total > 0)
            and (d["counter"] != "possession" or possessed > 0))


def stats_at_seq(match, teams, events, samples, seq, watermark, defs=None, *, actions, raw):
    """match: the matches row; teams: its matchTeams rows; events/samples/actions/raw: its canonicalEvents,
    possessionSamples, spadlActions and rawEvents rows (raw needs typeId, contestantId and payload, or eventSeq
    and, for VAR rows, qualifier).
    watermark: min(matchWatermarks.seq, spadlSeq). Empty when seq is outside 0..watermark."""
    if match is None or not 0 <= seq <= watermark:
        return []
    caps = json.loads(match.get("capabilities") or "{}")
    home = match.get("homeContestantId") or next((t["contestantId"] for t in teams if t["position"] == "home"), None)
    defs = [d for d in (defs or definitions()) if d["enabled"]]
    final = [a for a in actions if a["finalSeq"] <= seq]
    sent = [r for r in raw if r["typeId"] in (CARD, VAR) and _event_seq(r) is not None and _event_seq(r) <= seq]
    cards = [r for r in sent if r["typeId"] == CARD]
    overturns = [(r, q) for r in sent if r["typeId"] == VAR for q in [_qualifiers(r)]
                 if q.get(VAR_OUTCOME) == "goal-overturned"]

    clock = max((e["videoSeconds"] for e in events if e["seq"] <= seq and e["videoSeconds"] is not None), default=None)
    owned = {}
    for s in sorted(samples, key=lambda s: s["sampleId"]):
        if clock is not None and s["videoSeconds"] <= clock:
            owned[s["contestantId"]] = owned.get(s["contestantId"], 0) + s["durationSeconds"]
    total_owned = sum(owned.values())

    counted = {}  # statId -> [(teamId, against, hit)]
    for d in defs:
        facts = []
        if d["counter"] == "cards":
            facts = [(r["contestantId"], False, True) for r in cards]
        elif d["counter"] not in ("possession", "retired"):
            types = set(d["actionTypes"])
            facts = [(a["teamId"], d["counter"] == "opponent_count", _hit(d, a, home)) for a in final
                     if a["typeName"] in types and (d["bodypart"] is None or a["bodypartName"] == d["bodypart"])]
            if d["counter"] == "goals":
                facts += [(a["teamId"], True, True) for a in final if a["resultName"] == "owngoal"]
                facts += [(r["contestantId"], OWN_GOAL in q, -1) for r, q in overturns]
        counted[d["statId"]] = facts

    scopes = [(None, "Both teams")] + [(t["contestantId"], t["name"]) for t in
                                       sorted(teams, key=lambda t: t["position"] != "home")]
    out = []
    for team, name in scopes:
        for d in sorted(defs, key=lambda d: d["displayOrder"]):
            facts = [hit for t, against, hit in counted[d["statId"]]
                     if team is None or (t != team if against else t == team)]
            hits, total = sum(facts), len(facts)
            available = _available(d, caps, total, total_owned)
            if not available:
                value = None
            elif d["counter"] == "accuracy":
                value = round(100 * hits / total, 1)
            elif d["counter"] == "possession":
                value = round(100 * (owned.get(team, 0) if team else total_owned) / total_owned, 1)
            else:
                value = hits
            out.append({"statId": f"{team or 'all'}:{d['statId']}", "kind": d["statId"], "contestantId": team,
                        "label": f"{name} {d['label']}", "value": value, "available": available, "unit": d["unit"],
                        "definition": d["definition"], "eventTypes": json.dumps(d["actionTypes"]), "complete": True})
    return out


def _event_seq(row):
    if "eventSeq" in row:
        return row["eventSeq"]
    return json.loads(row["payload"]).get("eventSeq")
