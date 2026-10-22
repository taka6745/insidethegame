"""GraphQL client against an in-process fake of Data API builder.

The fake evaluates the client's filter variables (eq/gt/gte/lt/lte, and/or), orderBy and
cursor pagination over rows built from the synthetic match itg-syn-0001 (not real data) and
its SPADL actions, and answers executeStatsAtSeq from a per-seq table.
test_graphql_live.py runs the same client against the real local DAB when it is up.
"""
import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest

from narrative_engine.devtools.fake_agents import FakeAgents
from narrative_engine.match_data import EtlBehind
from narrative_engine.match_data.etl_graphql import GraphQLError, GraphQLMatchData, spell_rows, trend_rows
from narrative_engine.devtools.fixture_data import FixtureMatchData
from narrative_engine.core.models import MatchClock
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.devtools.targets import StaticTargets, default_targets
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink, read_notifications

FIXTURES = Path(__file__).parent / "fixtures"
MATCH = "itg-syn-0001-local"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
ACTIONS = FIXTURES / "itg-syn-0001-spadl.json"
ENTITY_TYPES = {"matches": "Match", "rawEvents": "RawEvent", "keyEvents": "KeyEvent", "spadlActions": "SpadlAction",
                "matchWatermarks": "MatchWatermark"}  # singular names from etl/dab/dab-config.json
OPS = {"eq": lambda a, b: a == b, "neq": lambda a, b: a != b, "gt": lambda a, b: a > b,
       "gte": lambda a, b: a >= b, "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b,
       "startsWith": lambda a, b: a.startswith(b)}


def stat_rows(shots):
    return [{"statId": f"{t}:{k}", "kind": k, "contestantId": t, "value": v, "available": True, "unit": u}
            for t in ("c-riv", "c-har") for k, v, u in (("possession", 50.0, "%"), ("shots", shots, ""))]


STATS = {1: stat_rows(0), 300: stat_rows(4), 800: stat_rows(9)}  # executeStatsAtSeq answers, by seq


def served_trends(seq):
    """executeTrendsAtSeq stand-in: possession per team; Riverside's half field tilt high from seq 300; a
    disabled trend (served without flags)."""
    share = round(0.5 + min(seq, 600) / 6000, 4)
    row = lambda trend, team, window, value, baseline=None, level=None, change=None, enabled=True: {
        "trendId": trend, "label": trend.replace("_", " "), "meaning": f"what {trend} measures", "unit": "share",
        "contestantId": team, "window": window, "minutes": 5, "value": value, "baseline": baseline,
        "delta": None if baseline is None else round(value - baseline, 4), "level": level, "change": change,
        "enabled": enabled}
    rows = [row("possession", t, "match", v, level="high" if v >= 0.55 else None)
            for t, v in (("c-riv", share), ("c-har", round(1 - share, 4)))] + [row("ppda", "c-riv", "half", 22.0,
                                                                                   enabled=False)]
    if seq >= 300:
        rows.append(row("field_tilt", "c-riv", "half", 0.74, 0.52, "high", "rising"))
    return rows


def served_spells(seq):
    return [{"trendId": "territory_spell", "contestantId": "c-riv", "periodId": 1, "fromLabel": "21'",
             "toLabel": "25'", "minutes": 5, "ongoing": False, "enabled": True}] if seq >= 500 else []


trends, spells = (lambda seq: trend_rows(served_trends(seq))), (lambda seq: spell_rows(served_spells(seq)))
FIXTURE = FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS, stats=STATS, actions_path=ACTIONS,
                           trends=trends, spells=spells)


def matches_filter(row, f):
    if "and" in f:
        return all(matches_filter(row, c) for c in f["and"])
    if "or" in f:
        return any(matches_filter(row, c) for c in f["or"])
    (column, ops), = f.items()
    return all(OPS[op](row[column], value) for op, value in ops.items())


class FakeDab:
    page_cap = 50

    def __init__(self):
        with open(FIXTURES / "itg-syn-0001.jsonl") as f:
            ma1 = {**json.loads(f.readline()), "matchId": MATCH}
        self.tables = {
            "matches": [{"matchId": MATCH, "payload": json.dumps(ma1)}],
            "rawEvents": [{**{k: e[k] for k in ("id", "seq", "eventId", "typeId", "periodId", "timeMin", "timeSec",
                                                "contestantId", "eventSeq")}, "matchId": MATCH, "payload": json.dumps(e)}
                          for e in FIXTURE.raw],
            "keyEvents": [{**k, "matchId": MATCH} for k in FIXTURE.keys],
            "spadlActions": [{**a, "matchId": MATCH} for a in FIXTURE.actions_rows],
            "matchWatermarks": [{"matchId": MATCH, "seq": max(e["eventSeq"] for e in FIXTURE.raw),
                                 "spadlSeq": max(e["seq"] for e in FIXTURE.raw)}],
        }
        self.requests = []

    def stats(self, seq):
        """statsAtSeq: [] above spadlSeq, as the procedure answers."""
        if seq > self.tables["matchWatermarks"][0]["spadlSeq"]:
            return []
        return STATS[max(s for s in STATS if s <= seq)]

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        query, variables = body["query"], body["variables"]
        if "bogus" in query:
            return httpx.Response(400, json={"errors": [{"message": "unknown field bogus"}]})
        if "executeStatsAtSeq(matchId: $m, seq: $s)" in query:
            rows = self.stats(variables["s"]) if variables["m"] == MATCH else []
            return httpx.Response(200, json={"data": {"executeStatsAtSeq": rows}})
        for procedure, answer in (("executeTrendsAtSeq", served_trends), ("executeTrendSpellsAtSeq", served_spells)):
            if f"{procedure}(matchId: $m, seq: $s)" in query:
                behind = variables["s"] > self.tables["matchWatermarks"][0]["spadlSeq"] or variables["m"] != MATCH
                fields = re.search(r"seq: \$s\) \{ (.*?) \}", query).group(1).split()
                rows = [] if behind else [{f: r[f] for f in fields} for r in answer(variables["s"])]
                return httpx.Response(200, json={"data": {procedure: rows}})
        entity = re.search(r"\{ (\w+)\(filter", query).group(1)
        assert f"$f: {ENTITY_TYPES[entity]}FilterInput" in query
        rows = [r for r in self.tables[entity] if matches_filter(r, variables["f"])]
        if order := re.search(r"orderBy: \{(.*?)\}", query):
            for column, direction in reversed([part.split(": ") for part in order.group(1).split(", ")]):
                rows.sort(key=lambda r: r[column], reverse=direction == "DESC")
        start = int(variables["after"] or 0)
        size = min(variables["first"], self.page_cap)
        fields = re.search(r"items \{ (.*?) \}", query).group(1).split()
        page = [{f: r[f] for f in fields} for r in rows[start:start + size]]  # only the selected fields
        more = start + size < len(rows)
        return httpx.Response(200, json={"data": {entity: {"items": page, "hasNextPage": more,
                                                           "endCursor": str(start + size) if more else None}}})


def client(dab):
    return GraphQLMatchData("http://dab/graphql", httpx.AsyncClient(transport=httpx.MockTransport(dab)),
                            stats_wait=0)


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def dab():
    return FakeDab()


def test_match_info_from_the_ma1_payload(dab):
    info = run(client(dab).match_info(MATCH))
    assert (info.home.name, info.away.code, info.player("p-riv-09")) == ("Riverside FC", "HAR", "Mensah")


def test_events_cross_half_time_and_stop_at_the_second(dab):
    c = client(dab)
    for start, end, sec in [(MatchClock(1, 46), MatchClock(2, 46), 59), (MatchClock(1, 23), MatchClock(1, 23), 9),
                            (MatchClock(1, 0), MatchClock(2, 95), 59)]:
        got = run(c.events(MATCH, start, end, sec))
        assert got == sorted(run(FIXTURE.events(MATCH, start, end, sec)), key=lambda e: e["seq"])
    assert len(got) == len(FIXTURE.raw) > FakeDab.page_cap  # followed the cursor across pages


def test_ledger_period_end_and_related_event(dab):
    c = client(dab)
    ledger = run(c.key_events(MATCH, MatchClock(2, 53), 34))
    assert [k["keyType"] for k in ledger][-2:] == ["Goal", "VarOverturn"]
    assert len(run(c.key_events(MATCH, MatchClock(1, 23), 8))) == 0
    assert run(c.period_end(MATCH, 1)) == MatchClock(1, 47)
    assert run(c.period_end(MATCH, 2)) == MatchClock(2, 95)
    assert run(c.period_end(MATCH, 3)) is None
    assert run(c.raw_event(MATCH, "c-har", 405))["typeId"] == 16


def test_event_seq_is_the_latest_ma3_rows_canonical_seq_up_to_the_horizon(dab):
    for row in dab.tables["rawEvents"]:
        row["eventSeq"] = row["seq"] * 10
    dab.tables["matchWatermarks"][0]["seq"] *= 10
    c = client(dab)
    upto = [e for e in FIXTURE.raw if (e["periodId"], e["timeMin"], e["timeSec"]) <= (1, 23, 9)]
    assert run(c.event_seq(MATCH, MatchClock(1, 23), 9)) == max(e["seq"] for e in upto) * 10
    assert run(c.event_seq("unknown", MatchClock(1, 23), 9)) is None
    goal = next(e for e in FIXTURE.raw if e["typeId"] == 16)
    assert run(c.event_seq_of(MATCH, goal["id"])) == goal["seq"] * 10 and run(c.event_seq_of(MATCH, -1)) is None


def test_ma3_reads_stop_at_the_committed_seq(dab):
    """Rows SQL holds past matchWatermarks.seq are unreachable; a clock range holding some is not complete."""
    c, raw = client(dab), sorted(dab.tables["rawEvents"], key=lambda r: r["seq"])
    cut = raw[len(raw) // 2]
    dab.tables["matchWatermarks"][0]["seq"] = cut["eventSeq"]
    before = MatchClock(cut["periodId"], cut["timeMin"] - 1)
    assert all(e["eventSeq"] <= cut["eventSeq"] for e in run(c.events(MATCH, MatchClock(1, 0), before)))
    assert run(c.event_seq(MATCH, before)) <= cut["eventSeq"]
    later = next(r for r in raw if r["eventSeq"] > cut["eventSeq"])
    assert run(c.event_seq_of(MATCH, later["id"])) is None
    assert run(c.period_end(MATCH, 2)) is None  # its End row is past the watermark
    with pytest.raises(EtlBehind):
        run(c.events(MATCH, MatchClock(1, 0), MatchClock(2, 95)))
    with pytest.raises(EtlBehind):
        run(c.event_seq(MATCH, MatchClock(2, 95)))
    queries = [r["variables"].get("f") for r in dab.requests if "rawEvents" in r["query"]]
    assert all("eventSeq" in json.dumps(f) for f in queries)


def test_actions_are_the_ones_settled_in_the_seq_span_across_pages(dab):
    c, final = client(dab), dab.tables["matchWatermarks"][0]["spadlSeq"]
    for after, upto in [(0, 0), (0, 40), (100, 400), (0, final)]:
        got = run(c.actions(MATCH, after, upto))
        assert got == run(FIXTURE.actions(MATCH, after, upto))
        assert all(after < a["finalSeq"] <= upto for a in got)
    assert len(got) == len(FIXTURE.actions_rows) > FakeDab.page_cap  # followed the cursor across pages
    assert [a["actionId"] for a in got] == sorted(a["actionId"] for a in got)


def test_spadl_reads_wait_for_the_conversion_watermark(dab):
    watermark = dab.tables["matchWatermarks"][0]
    final = watermark["spadlSeq"]
    watermark["spadlSeq"] = 100
    c = client(dab)
    with pytest.raises(EtlBehind):
        run(c.actions(MATCH, 0, 200))
    with pytest.raises(EtlBehind):
        run(c.stats_at(MATCH, 200))
    assert run(c.actions(MATCH, 0, 100)) == run(FIXTURE.actions(MATCH, 0, 100))

    async def converted_after_two_polls():
        original, polls = c.spadl_seq, 0

        async def spadl_seq(match_id):
            nonlocal polls
            polls += 1
            if polls == 3:
                watermark["spadlSeq"] = final
            return await original(match_id)
        c.spadl_seq = spadl_seq
        return await c.actions(MATCH, 0, 200), polls
    rows, polls = run(converted_after_two_polls())
    assert polls == 3 and rows == run(FIXTURE.actions(MATCH, 0, 200))


def test_stats_at_reads_the_catalogue_at_the_seq(dab):
    c = client(dab)
    assert run(c.stats_at(MATCH, 450)) == STATS[300] == run(FIXTURE.stats_at(MATCH, 450))
    assert run(c.stats_at(MATCH, 0)) == [] and run(c.stats_at(MATCH, None)) == []
    dab.tables["matchWatermarks"].append({"matchId": "purged", "seq": 10_000, "spadlSeq": 10_000})
    with pytest.raises(EtlBehind):  # the procedure answers [] (here: an unknown match): never a partial table
        run(c.stats_at("purged", 5))


def test_trends_and_spells_are_read_at_the_seq_and_wait_for_spadl(dab):
    c = client(dab)
    assert run(c.trends_at(MATCH, 450)) == trends(450) == run(FIXTURE.trends_at(MATCH, 450))
    assert len(trends(450)) == 3 and not any(r["indicator"] == "ppda" for r in trends(450))  # disabled: left out
    assert trends(450)[2] == {"indicator": "field_tilt", "label": "field tilt", "meaning": "what field_tilt measures",
                              "unit": "share", "contestantId": "c-riv", "window": "half", "minutes": 5,
                              "value": 0.74, "previous": 0.52, "delta": 0.22, "level": "high", "trend": "rising"}
    assert run(c.spells_at(MATCH, 450)) == [] and run(c.spells_at(MATCH, 600)) == spells(600)
    assert run(c.trends_at(MATCH, 0)) == [] and run(c.spells_at(MATCH, None)) == []
    dab.tables["matchWatermarks"][0]["spadlSeq"] = 100
    with pytest.raises(EtlBehind):  # never past the SPADL watermark
        run(c.trends_at(MATCH, 200))
    with pytest.raises(EtlBehind):
        run(c.spells_at(MATCH, 200))
    dab.tables["matchWatermarks"].append({"matchId": "purged", "seq": 10_000, "spadlSeq": 10_000})
    with pytest.raises(EtlBehind):  # [] trend rows mean the procedure is behind, never "no trends"
        run(c.trends_at("purged", 5))
    assert run(c.spells_at("purged", 5)) == []  # no spells is an answer


def test_graphql_errors_are_raised(dab):
    with pytest.raises(GraphQLError, match="bogus"):
        run(client(dab)._post("{ bogus }", {}))


def test_orchestrator_over_graphql_matches_the_fixture_run(dab):
    messages = [m for _, m in read_notifications(NOTIFICATIONS) if m]

    def full_run(data):
        agents, store = FakeAgents(), MemoryStore()
        buckets = default_targets()[:2]  # every bucket reads the same data; two keep the fake DAB quick
        engine = MatchOrchestrator(MATCH, data, agents, store, MemorySink(store), targets=StaticTargets(buckets))

        async def go():
            for m in messages:
                await engine.handle(m)
        asyncio.run(go())
        return agents.calls

    via_graphql, via_fixture = full_run(client(dab)), full_run(FIXTURE)
    assert via_graphql == via_fixture
    assert any("shot, success" in v.get("match_events", "") for _, v in via_fixture)
    assert any("| Shots (on target) | 9 (n/a) |" in v["game_state_statistics"] for _, v in via_fixture)
    analyses = [v for a, v in via_fixture if a == "analyse"]
    assert analyses and any("  field tilt: RIV 0.74 (high, rising from 0.52)" in v["match_trends"] for v in analyses)
    assert any("territory spell" in v["match_trends"] for v in analyses)
