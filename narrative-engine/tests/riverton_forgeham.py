"""The checked-in Riverton Rovers–United GRF recording (synthetic) as engine test data: its MA1/MA3 replay
(data-generation/recordings), the ETL's SPADL fixture for it (etl/tests/fixtures; same canonical
seqs as the replay's `eventSeq`), catalogue golden stats, and the ETL notifications and keyEvents
rows the replay produces (etl/contracts/README.md: key event types, MinuteClosed per minute)."""
import json
from pathlib import Path

from narrative_engine.core.models import parse_notification
from doubles.fixture_data import FixtureMatchData

ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / "data-generation" / "recordings" / "riverton-forgeham-grf.opta-stream.jsonl"
ACTIONS = ROOT / "etl" / "tests" / "fixtures" / "spadl-riverton-forgeham.json"
GOLDEN = ROOT / "etl" / "tests" / "fixtures" / "catalogue-golden.json"
MATCH = "riverton-forgeham-1a2b3c4d"
T = "2026-10-20T15:00:00Z"


def ma3():
    return [m for m in map(json.loads, REPLAY.read_text(encoding="utf-8").splitlines()) if m["feed"] == "MA3"]


def has_q(e, q):
    return any(x["qualifierId"] == q for x in e.get("qualifier", []))


def key_type(e):
    t = e["typeId"]
    if t == 16:
        return ("OwnGoal", None) if has_q(e, 28) else ("Goal", "penalty" if has_q(e, 9) else None)
    if t in (13, 14, 15) and has_q(e, 9):
        return "PenaltyMissed", None
    if t == 4 and e["outcome"] == 0 and has_q(e, 9):
        return "PenaltyAwarded", "conceded"
    if t == 17 and (has_q(e, 32) or has_q(e, 33)):
        return "RedCard", "second-yellow" if has_q(e, 32) else None
    return None


def key_rows():
    return [{"id": e["id"], "keyType": k[0], "detail": k[1], "typeId": e["typeId"], "contestantId": e["contestantId"],
             "playerId": e.get("playerId"), "periodId": e["periodId"], "timeMin": e["timeMin"], "timeSec": e["timeSec"],
             "eventTime": T, "relatedEventId": None} for e in ma3() if (k := key_type(e))]


def timeline():
    """(body, seq) in the order the ETL sends them, with the canonical seq of the latest MA3 row the
    ETL holds when it sends each: key events and period changes as they happen, and a MinuteClosed
    once a minute's last row is followed by a later minute (or the match ends)."""
    keys = {k["id"]: k for k in key_rows()}
    out, last, periods = [], None, set()
    rows = ma3()
    for e in rows:
        clock = (e["periodId"], e["timeMin"])
        if last and clock != last:
            out.append(({"messageType": "MinuteClosed", "matchId": MATCH, "periodId": last[0], "timeMin": last[1],
                         "windowEnd": T}, e["eventSeq"]))
        last = clock
        if e["id"] in keys:
            out.append(({**keys[e["id"]], "messageType": "KeyEventDetected", "matchId": MATCH}, e["eventSeq"]))
        if e["typeId"] in (30, 32) and (e["typeId"], e["periodId"]) not in periods:
            periods.add((e["typeId"], e["periodId"]))
            out.append(({"messageType": "PeriodEnded" if e["typeId"] == 30 else "PeriodStarted", "matchId": MATCH,
                         "periodId": e["periodId"], "timeMin": e["timeMin"], "timeSec": e["timeSec"], "eventTime": T},
                        e["eventSeq"]))
    out.append(({"messageType": "MinuteClosed", "matchId": MATCH, "periodId": last[0], "timeMin": last[1],
                 "windowEnd": T}, rows[-1]["eventSeq"]))
    return out


def notifications():
    return [body for body, _ in timeline()]


def messages():
    return [m for m in map(parse_notification, notifications()) if m]


def golden_stats():
    """The ETL's golden executeStatsAtSeq values at its sampled seqs, as rows keyed by seq."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    units = {r["statId"]: r["unit"] for r in golden["final"]}
    meanings = {r["statId"]: r["definition"] for r in golden["final"]}

    def row(stat_id, value, available):
        scope, kind = stat_id.split(":")
        return {"statId": stat_id, "kind": kind, "contestantId": None if scope == "all" else scope, "value": value,
                "available": available, "unit": units[stat_id], "definition": meanings[stat_id]}
    return {int(seq): [row(*r) for r in rows] for seq, rows in golden["prefixes"].items()}


def data(stats=None):
    return FixtureMatchData(REPLAY, stats=stats, actions_path=ACTIONS, keys=key_rows())
