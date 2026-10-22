"""reference/spadl.py against socceraction 1.5.3 (test-only oracle) on every recording, and its live finalisation.

Oracle: the run's MA3 rows as a Stats Perform MA3 document -> MA3JSONParser via OptaLoader.events ->
opta.convert_to_actions -> SPADLSchema.validate. ALLOWED lists accepted differences (none).
"""
import bisect
import json
import math
import warnings
from collections import Counter

import pytest

import v2_stream
from reference import spadl

with warnings.catch_warnings():  # The oracle's pinned dependencies warn on import.
    warnings.simplefilter("ignore")
    from socceraction.data.opta import OptaLoader
    from socceraction.spadl import SPADLSchema
    from socceraction.spadl import opta as spadl_opta

pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning", "ignore::DeprecationWarning", "ignore::UserWarning")
ALLOWED = {}  # {(fixture, actionId, column): reason}; keep empty
COLUMNS = {"action_id": "actionId", "original_event_id": "originalEventId", "period_id": "periodId",
           "time_seconds": "timeSeconds", "team_id": "teamId", "player_id": "playerId", "start_x": "startX",
           "start_y": "startY", "end_x": "endX", "end_y": "endY", "type_id": "typeId", "result_id": "resultId",
           "bodypart_id": "bodypartId"}


def run(fixture):
    stream = v2_stream.build(fixture=fixture)
    home = next(c["id"] for c in stream[0]["contestant"] if c["position"] == "home")
    return stream, home, [m for m in stream if m.get("feed") == "MA3"]


def oracle(stream, tmp_path):
    """socceraction's actions for the run (real MA3 sends x/y 0 where ours are null; its parser needs them)."""
    ma1 = stream[0]
    events = [{**{k: m[k] for k in ("id", "eventId", "typeId", "periodId", "timeMin", "timeSec", "contestantId",
                                    "outcome", "timeStamp", "qualifier")},
               "x": m["x"] or 0.0, "y": m["y"] or 0.0,
               **({"playerId": m["playerId"], "playerName": m["playerName"]} if m.get("playerId") else {})}
              for m in stream if m.get("feed") == "MA3"]
    document = {"matchInfo": {"id": ma1["matchId"], "contestant": [{k: c[k] for k in ("id", "position", "name")}
                                                                   for c in ma1["contestant"]]},
                "liveData": {"event": events}}
    (tmp_path / "ma3.json").write_text(json.dumps(document), encoding="utf-8")
    loader = OptaLoader(str(tmp_path), parser="statsperform", feeds={"ma3": "ma3.json"})
    home = next(c["id"] for c in ma1["contestant"] if c["position"] == "home")
    actions = spadl_opta.convert_to_actions(loader.events(ma1["matchId"]), home)
    return SPADLSchema.validate(actions).to_dict("records")


@pytest.mark.parametrize("fixture", v2_stream.FIXTURES)
def test_whole_match_equals_socceraction(fixture, tmp_path):
    stream, home, ma3 = run(fixture)
    expected, got = oracle(stream, tmp_path), spadl.actions(ma3, home)
    assert len(got) == len(expected) > 2500
    differences = {}
    for e, a in zip(expected, got):
        for theirs, ours in COLUMNS.items():
            value = e[theirs]
            value = None if isinstance(value, float) and math.isnan(value) else value
            if value != a[ours]:
                differences[(fixture, a["actionId"], ours)] = (value, a[ours])
    assert {k: v for k, v in differences.items() if k not in ALLOWED} == {}
    assert {a["typeName"] for a in got} >= {"pass", "cross", "dribble", "shot", "clearance", "interception", "foul"}


@pytest.mark.parametrize("fixture", v2_stream.FIXTURES)
def test_incremental_equals_whole_match(fixture):
    """The post-processor's loop at every watermark P: restart from the last stored non-dribble action,
    convert the rows with eventSeq <= P, store the actions final at P."""
    stream, home, ma3 = run(fixture)
    whole = spadl.actions(ma3, home)
    event_seqs, index = [m["eventSeq"] for m in ma3], {m["id"]: i for i, m in enumerate(ma3)}
    stored = []
    for watermark in range(1, sum(m.get("type") == "MatchEvent" for m in stream) + 1):
        restart = next((a for a in reversed(stored) if a["originalEventId"] is not None), None)
        start = index[restart["originalEventId"]] if restart else 0
        tail = ma3[start:bisect.bisect_right(event_seqs, watermark)]
        first = (restart["actionId"], restart["finalSeq"]) if restart else (0, 0)
        for a in spadl.final_actions(tail, home, *first):
            assert a["finalSeq"] <= watermark
            if a["actionId"] < len(stored):
                assert a == stored[a["actionId"]]
            else:
                stored.append(a)
    assert stored == whole


@pytest.mark.parametrize("fixture", v2_stream.FIXTURES)
def test_finalisation(fixture):
    stream, home, ma3 = run(fixture)
    whole = spadl.actions(ma3, home)
    assert [a["actionId"] for a in whole] == list(range(len(whole)))
    finals = [a["finalSeq"] for a in whole]
    assert finals == sorted(finals) and all(a["finalSeq"] >= a["seq"] for a in whole)
    shots = [a for a in whole if a["sourceTypeId"] in spadl.SHOT_EVENTS]
    assert len(shots) >= 10 and all(a["finalSeq"] == a["seq"] for a in shots)  # Shots and goals at once.
    for period in (1, 2):  # period_end finalises the whole period.
        end = min(m["eventSeq"] for m in ma3 if m["typeId"] == spadl.END and m["periodId"] == period)
        assert max(a["finalSeq"] for a in whole if a["periodId"] == period) <= end
    # Others: the next one or two actions (more only for the few that wait for a deflection check or period_end).
    seqs = [a["seq"] for a in whole]
    later = Counter(min(bisect.bisect_right(seqs, a["finalSeq"]) - 1 - i, 3) for i, a in enumerate(whole))
    assert later[1] + later[2] > 0.85 * len(whole) and later[3] < 0.02 * len(whole)


def test_live_prefix_holds_back_unfinished_actions():
    _, home, ma3 = run("chelsea-united")
    pass_row = next(i for i, m in enumerate(ma3) if m["typeId"] == spadl.PASS and m["periodId"] == 1 and i > 100)
    prefix = [m for m in ma3 if m["eventSeq"] <= ma3[pass_row]["eventSeq"]]
    live = spadl.convert(prefix, home, closed=False)
    assert live[-1]["finalSeq"] is None  # The pass's last row cannot know what follows it.
    final = spadl.final_actions(prefix, home)
    assert final == spadl.actions(ma3, home)[:len(final)] and len(final) < len(live)


def test_extensions():
    _, home, ma3 = run("chelsea-united")
    whole = spadl.actions(ma3, home)
    by_id = {m["id"]: m for m in ma3}
    for a in whole:
        assert set(a) == set(spadl.COLUMNS)
        if a["originalEventId"] is None:  # Inserted dribble.
            assert a["typeName"] == "dribble" and a["sourceEventId"] is None and a["sourceTypeId"] is None
            assert not (a["fromShotOffTarget"] or a["defensiveBlock"])
        else:
            m = by_id[a["originalEventId"]]
            assert (a["sourceEventId"], a["sourceTypeId"], a["seq"]) == (m["sourceEventId"], m["typeId"], m["eventSeq"])
            assert a["clockSeconds"] == m["timeMin"] * 60 + m["timeSec"] and a["videoSeconds"] == m["videoSeconds"]
            q = {x["qualifierId"] for x in m["qualifier"]}
            assert (a["fromShotOffTarget"], a["defensiveBlock"]) == (190 in q, 94 in q)
        assert a["startZone"] == spadl.zone(a["startX"], a["startY"], a["teamId"], home)
    saves = [a for a in whole if a["typeName"] == "keeper_save"]  # 3 keeper saves, 1 off-target touch, no block
    assert (len(saves), sum(a["fromShotOffTarget"] for a in saves), sum(a["defensiveBlock"] for a in saves)) == (4, 1, 0)
    observed = [a for a in whole if a["bodypartObserved"]]
    assert observed and all(a["bodypartName"] in ("head", "other", "foot_left", "foot_right") for a in observed)
    assert not any(a["bodypartObserved"] for a in whole if a["typeName"] == "dribble" and a["originalEventId"] is None)


def test_zones_are_relative_to_the_acting_team():
    assert spadl.zone(100.0, 34.0, "home", "home") == "opp_box"
    assert spadl.zone(100.0, 34.0, "away", "home") == "own_box"
    assert spadl.zone(5.0, 34.0, "away", "home") == "opp_box"
    assert spadl.zone(80.0, 2.0, "home", "home") == "final_third"
    assert spadl.zone(50.0, 34.0, "away", "home") == "middle_third"
    assert spadl.zone(20.0, 1.0, "home", "home") == "defensive_third"
