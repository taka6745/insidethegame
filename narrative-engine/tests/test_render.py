"""Prompt rendering: snapshots over the Riverton Rovers–Forgeham United recording and the ETL's SPADL fixture for it
(tests/riverton_forgeham.py), plus the synthetic match itg-syn-0001 (etl/seeder; not real data)."""
import asyncio
import json
from pathlib import Path

import riverton_forgeham
from narrative_engine.context.builder import ContextBuilder
from narrative_engine.context.render import MatchInfo, describe_action, render_events, render_ledger, render_match, \
    render_stats, score
from narrative_engine.core.models import MatchClock
from narrative_engine.store.memory import MemoryStore

FIXTURES = Path(__file__).parent / "fixtures"
with open(FIXTURES / "itg-syn-0001.jsonl") as f:
    MESSAGES = [json.loads(line) for line in f]
INFO = MatchInfo.from_ma1(MESSAGES[0])
DATA = riverton_forgeham.data()
CU = DATA.info


def minute(period, minute_):
    """The minute-summary match_events of one Riverton Rovers–Forgeham United minute."""
    async def go():
        clock = MatchClock(period, minute_)
        return (await ContextBuilder(DATA, MemoryStore()).summary_variables(
            "m", clock, await DATA.events("m", clock, clock)))["match_events"]
    return asyncio.run(go())


def test_match_info_reads_teams_and_lineups():
    assert (INFO.home.name, INFO.home.code, INFO.away.name) == ("Riverside FC", "RIV", "Harbour Athletic")
    assert INFO.player("p-riv-09") == "Mensah" and INFO.synthetic
    assert "Synthetic" in render_match(INFO)


def test_goal_minute_snapshot():
    assert minute(2, 71) == """\
72' (second half)
  71:10 RVR Joel Hartigan: take_on, success, box
  71:13 RVR Joel Hartigan: cross, success, left foot, left wing → box
  71:13 FGU Yusuf Karabey: foul, fail, own box
  71:13 key event: Penalty to Riverton Rovers, conceded by Yusuf Karabey (Forgeham United)
  71:16 RVR Rory Calloway: shot_penalty, success, left foot, box
  71:16 key event: Goal for Riverton Rovers, Rory Calloway (penalty)
  71:38 RVR Felix Adeyinka: cross, success, right foot, left wing → box
  71:43 FGU Moses Ekwueme: tackle, fail, own box
  71:47 RVR Felix Adeyinka: cross, success, right foot, left wing → box
  71:52 RVR Sami Lindqvist: take_on, success, box
  71:55 RVR Felix Adeyinka: cross, success, left foot, left wing → box
  totals: RVR passes 10/11 completed, carries 7, final-third entries 1, box entries 6; FGU passes 0/0 completed, \
carries 1, final-third entries 1"""


def test_penalty_and_set_piece_minute_snapshot():
    assert minute(1, 9) == """\
10' (first half)
  09:01 FGU Jamal Whitcombe: interception, fail, left midfield
  09:14 RVR Ilan Petrakis: cross, success, right foot, right wing → box
  09:20 FGU Theo Marchetti: clearance, success, left foot, own third → box
  09:31 RVR Sami Lindqvist: foul, fail, own box
  09:31 key event: Penalty to Forgeham United, conceded by Sami Lindqvist (Riverton Rovers)
  09:35 FGU Callum Brightwell: shot_penalty, success, left foot, box
  09:35 key event: Goal for Forgeham United, Callum Brightwell (penalty)
  09:42 FGU Theo Marchetti: interception, fail, own third
  09:53 RVR Dario Mensforth: foul, fail, left wing
  09:59 FGU Luca Ferrandi: freekick_crossed, fail, left foot, own third → midfield
  totals: RVR passes 8/12 completed, carries 9, final-third entries 2, box entries 2; FGU passes 1/4 completed, \
carries 3, final-third entries 1"""


def test_period_end_minute_settles_every_action():
    assert minute(1, 46) == """\
45+2' (first half)
  46:18 first half ends
  totals: FGU passes 8/8 completed, carries 6, final-third entries 1, box entries 2"""
    assert minute(1, 45).splitlines()[0] == "45+1' (first half)"


def test_every_action_is_shown_once_across_the_minute_windows():
    """Minute windows split by the settling seq, so each action lands in exactly one minute summary."""
    async def go():
        builder, seen = ContextBuilder(DATA, MemoryStore()), []
        for clock in sorted({MatchClock(e["periodId"], e["timeMin"]) for e in DATA.raw}):
            before = await builder._seq("m", MatchClock(clock.periodId, clock.timeMin - 1))
            seen += [a["actionId"] for a in await DATA.actions("m", before, await builder._seq("m", clock))]
        return seen
    assert sorted(asyncio.run(go())) == [a["actionId"] for a in DATA.actions_rows]


def test_late_settled_actions_go_under_the_window_heading():
    action = next(a for a in DATA.actions_rows if a["typeName"] == "tackle")
    text = render_events(CU, [action], start=MatchClock(action["periodId"], int(action["clockSeconds"]) // 60 + 1))
    assert len(text.splitlines()) == 3 and text.splitlines()[1].startswith(
        f"  {int(action['clockSeconds']) // 60:02d}:")


def test_action_lines_use_spadl_names_and_team_relative_places():
    cross = {"typeName": "cross", "resultName": "success", "bodypartName": "foot_left", "bodypartObserved": True,
             "teamId": "forgeham", "startZone": "final_third", "startY": 60.0, "endZone": "opp_box", "endY": 34.0}
    assert describe_action(cross, CU) == "cross, success, left foot, right wing → box"  # away: y is mirrored
    assert describe_action({**cross, "teamId": "riverton", "bodypartObserved": False}, CU) == \
        "cross, success, left wing → box"
    assert describe_action({**cross, "typeName": "tackle"}, CU) == "tackle, success, left foot, right wing"
    assert render_events(CU, []) == "No recorded events."


def test_keeper_saves_that_are_not_goalkeeper_saves_say_so():
    # No Riverton Rovers–Forgeham United keeper_save is an outfield block in the current render: mark a save as one.
    block = {**next(a for a in DATA.actions_rows if a["typeName"] == "keeper_save"), "defensiveBlock": True}
    assert describe_action(block, CU).startswith("keeper_save, success, outfield block, not a goalkeeper save")
    wide = next(a for a in DATA.actions_rows if a["fromShotOffTarget"])
    assert "touch of a shot going wide, not a save" in describe_action(wide, CU)
    save = next(a for a in DATA.actions_rows if a["typeName"] == "keeper_save")
    assert "not a" not in describe_action(save, CU)


def test_stats_table_snapshot():
    rows = riverton_forgeham.golden_stats()[11133]
    table, meanings = render_stats(rows, CU, MatchClock(2, 91), riverton_forgeham.key_rows()).split("\nWhat each counts:\n")
    # The catalogue's definitions follow the table: box entries can outnumber final-third entries, and say so.
    assert "- Box entries: " in meanings and "can outnumber final-third entries" in meanings
    assert len(meanings.splitlines()) == 9
    assert table == """\
As of 90+2' (second half)
Score: Riverton Rovers (home) 1 - 1 Forgeham United (away)
| Statistic | Riverton Rovers | Forgeham United |
| --- | --- | --- |
| Possession (share of ball time) | 63.6% | 36.4% |
| Shots (on target) | 9 (3) | 5 (2) |
| Passes (completed) | 941 (756) | 462 (335) |
| Crosses (completed) | 88 (63) | 42 (23) |
| Final-third entries | 68 | 66 |
| Box entries | 157 | 57 |
| Corners | 2 | 3 |
| Fouls | 19 | 11 |
| Cards | 0 | 0 |"""
    assert render_stats([], CU, MatchClock(1, 3)) == "No statistics yet."
    unavailable = [{**r, "available": False, "value": None} if r["kind"] == "shots_on_target" else r for r in rows]
    assert "| Shots (on target) | 9 (n/a) | 5 (n/a) |" in render_stats(unavailable, CU, MatchClock(2, 91))


def test_score_counts_own_goals_for_the_opponent_and_removes_var_overturns():
    keys = [{"keyType": "Goal", "contestantId": "c-har"}, {"keyType": "OwnGoal", "contestantId": "c-har"},
            {"keyType": "VarOverturn", "detail": "goal-overturned", "contestantId": "c-har"},
            {"keyType": "VarOverturn", "detail": "own-goal-overturned", "contestantId": "c-har"},
            {"keyType": "RedCard", "contestantId": "c-riv"}]
    assert score(keys, INFO) == {"c-riv": 0, "c-har": 0}
    assert score(keys[:2], INFO) == {"c-riv": 1, "c-har": 1}


def test_ledger_explains_who_benefits_and_marks_overturns():
    rows = [
        {"id": 1, "keyType": "Goal", "detail": None, "contestantId": "c-har", "playerId": "p-har-09",
         "periodId": 2, "timeMin": 52, "timeSec": 24},
        {"id": 2, "keyType": "VarOverturn", "detail": "goal-overturned", "contestantId": "c-har",
         "playerId": "p-har-09", "periodId": 2, "timeMin": 53, "timeSec": 34},
        {"id": 3, "keyType": "PenaltyAwarded", "detail": "conceded", "contestantId": "c-har", "playerId": "p-har-05",
         "periodId": 1, "timeMin": 37, "timeSec": 41},
        {"id": 4, "keyType": "OwnGoal", "detail": None, "contestantId": "c-riv", "playerId": "p-riv-05",
         "periodId": 2, "timeMin": 84, "timeSec": 36},
    ]
    lines = render_ledger(rows, INFO, overturned={1}).splitlines()
    assert lines[0] == "- 38' 37:41: Penalty to Riverside FC, conceded by Bauer (Harbour Athletic)"
    assert lines[1].endswith("Goal for Harbour Athletic, Adeyemi [later overturned by VAR] "
                             "(score now Riverside FC 0-1 Harbour Athletic)")
    assert "VAR overturns the Harbour Athletic goal (Adeyemi)" in lines[2]
    assert lines[2].endswith("(score now Riverside FC 0-0 Harbour Athletic)")
    assert lines[3].endswith("(score now Riverside FC 0-1 Harbour Athletic)")  # each goal line gives the score after it
    assert "Own goal by Byrne (Riverside FC), counts for Harbour Athletic" in lines[3]
