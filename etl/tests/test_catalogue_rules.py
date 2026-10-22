"""Counting rules of the SPADL stat catalogue on small synthetic actions.

Own goals and fouls count for the other team; shots on target and blocked shots read the source Opta type and
the goal line; entries cross zones relative to the acting team; capabilities decide availability; snapshots
read only actions final at their seq; cards and VAR overturns come from MA3 rows bounded by eventSeq.
"""
import json

from reference import catalogue

TEAMS = [{"contestantId": "chelsea", "name": "Chelsea", "position": "home"},
         {"contestantId": "manutd", "name": "Manchester United", "position": "away"}]
MATCH = {"homeContestantId": "chelsea", "capabilities": json.dumps({"shotOutcomes": True})}


def action(type_name, seq=1, team="chelsea", result="success", body="foot", end_x=50.0, source_type=1,
           start_zone="middle_third", end_zone="middle_third", final=None):
    return {"teamId": team, "typeName": type_name, "resultName": result, "bodypartName": body, "endX": end_x,
            "sourceTypeId": source_type, "startZone": start_zone, "endZone": end_zone, "seq": seq,
            "finalSeq": seq if final is None else final}


def stats(actions, raw=(), seq=None, match=MATCH):
    seq = max((a["finalSeq"] for a in actions), default=0) if seq is None else seq
    rows = catalogue.stats_at_seq(match, TEAMS, [], [], seq, seq, actions=actions, raw=list(raw))
    return {(r["contestantId"] or "all", r["kind"]): r for r in rows}


def value(s, team, kind):
    return s[(team, kind)]["value"]


def test_goals_include_the_opponents_own_goals():
    s = stats([action("shot"), action("shot_penalty", result="success"), action("shot", result="fail"),
               action("bad_touch", team="manutd", result="owngoal"), action("shot", team="manutd")])
    assert (value(s, "chelsea", "goals"), value(s, "manutd", "goals"), value(s, "all", "goals")) == (3, 1, 4)
    assert (value(s, "chelsea", "shots"), value(s, "chelsea", "penalties")) == (3, 1)


def var(seq, team, own_goal=False, outcome="goal-overturned"):
    """An MA3 VAR decision (type 900, qualifier 901) as rawEvents stores it."""
    qualifier = [{"qualifierId": 901, "value": outcome}] + ([{"qualifierId": 28}] if own_goal else [])
    return {"typeId": 900, "contestantId": team, "payload": json.dumps({"eventSeq": seq, "qualifier": qualifier})}


VAR_ACTIONS = [action("shot", seq=1), action("bad_touch", seq=2, team="manutd", result="owngoal"), action("shot", seq=3),
               action("shot", seq=4, team="manutd")]
VAR_ROWS = [var(5, "chelsea"), var(6, "manutd", own_goal=True), var(7, "chelsea", outcome="goal-confirmed"),
            var(8, "manutd")]


def test_var_overturns_take_goals_back_from_their_seq():
    goals = lambda seq: tuple(value(stats(VAR_ACTIONS, VAR_ROWS, seq=seq), t, "goals") for t in ("chelsea", "manutd", "all"))
    assert goals(4) == (3, 1, 4)  # two goals and an own goal for Chelsea
    assert goals(5) == (2, 1, 3)  # Chelsea's goal overturned
    assert goals(6) == (1, 1, 2)  # United's own goal overturned: Chelsea lose it
    assert goals(7) == (1, 1, 2)  # a confirmed goal changes nothing
    assert goals(8) == (1, 0, 1)
    assert value(stats(VAR_ACTIONS, VAR_ROWS, seq=8), "chelsea", "shots") == 2  # the attempts stay


def test_fouls_won_are_the_opponents_fouls():
    s = stats([action("foul", result="fail"), action("foul", team="manutd", result="fail"),
               action("foul", team="manutd", result="fail")])
    assert (value(s, "chelsea", "fouls"), value(s, "chelsea", "fouls_won")) == (1, 2)
    assert (value(s, "manutd", "fouls_won"), value(s, "all", "fouls_won"), value(s, "all", "fouls")) == (1, 3, 3)


def test_pass_family_set_pieces_and_offsides():
    kinds = ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"]
    s = stats([action(k) for k in kinds] + [action("pass", result="offside"), action("cross", result="fail"),
                                            action("shot_freekick", result="fail")])
    assert (value(s, "chelsea", "passes"), value(s, "chelsea", "passes_completed"), value(s, "chelsea", "offsides")) == (10, 8, 1)
    assert value(s, "chelsea", "pass_accuracy") == 80.0
    assert (value(s, "chelsea", "crosses"), value(s, "chelsea", "crosses_completed"), value(s, "chelsea", "cross_accuracy")) == (4, 3, 75.0)
    assert (value(s, "chelsea", "corners"), value(s, "chelsea", "free_kicks"), value(s, "chelsea", "free_kick_shots")) == (2, 3, 1)
    assert (value(s, "chelsea", "throw_ins"), value(s, "chelsea", "goal_kicks")) == (1, 1)


def test_accuracy_is_unavailable_without_attempts():
    s = stats([action("shot")])
    assert s[("chelsea", "pass_accuracy")]["available"] is False and value(s, "chelsea", "pass_accuracy") is None


def test_on_target_and_blocked_read_the_goal_line_in_the_teams_frame():
    s = stats([action("shot", result="success", source_type=16),
               action("shot", result="fail", source_type=15, end_x=105.0),   # saved
               action("shot", result="fail", source_type=15, end_x=90.0),    # blocked
               action("shot", result="fail", source_type=13, end_x=105.0),   # missed
               action("shot", team="manutd", result="fail", source_type=15, end_x=0.0),   # away: saved
               action("shot", team="manutd", result="fail", source_type=15, end_x=12.0)])
    assert (value(s, "chelsea", "shots_on_target"), value(s, "chelsea", "blocked_shots")) == (2, 1)
    assert (value(s, "manutd", "shots_on_target"), value(s, "manutd", "blocked_shots")) == (1, 1)
    no_outcomes = stats([action("shot")], match={"homeContestantId": "chelsea",
                                                 "capabilities": json.dumps({"shotOutcomes": False})})
    assert no_outcomes[("chelsea", "shots_on_target")]["available"] is False


def test_entries_cross_into_the_zone():
    s = stats([action("pass", start_zone="middle_third", end_zone="final_third"),
               action("cross", start_zone="final_third", end_zone="opp_box"),
               action("dribble", start_zone="middle_third", end_zone="opp_box"),
               action("pass", start_zone="final_third", end_zone="final_third"),
               action("pass", result="fail", start_zone="middle_third", end_zone="opp_box"),
               action("take_on", start_zone="middle_third", end_zone="final_third")])
    assert (value(s, "chelsea", "final_third_entries"), value(s, "chelsea", "box_entries")) == (2, 2)


def test_headed_stats_follow_body_part_coverage():
    actions = [action("pass", body="head"), action("shot", body="head"), action("clearance", body="head"),
               action("pass", body="foot_left")]
    passes = ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short",
              "goalkick"]
    partial = stats(actions, match={"homeContestantId": "chelsea", "capabilities": json.dumps(
        {"bodyParts": False, "bodyPartEventTypes": ["pass"], "bodyPartActionTypes": passes + ["shot"]})})
    assert value(partial, "chelsea", "headed_passes") == 1
    assert partial[("chelsea", "headed_shots")]["available"] is False  # shot_penalty, shot_freekick uncertified
    provider_only = stats(actions, match={"homeContestantId": "chelsea", "capabilities": json.dumps(
        {"bodyParts": False, "bodyPartEventTypes": ["pass", "shot", "goal"]})})  # SPADL coverage is what counts
    assert provider_only[("chelsea", "headed_passes")]["available"] is False
    assert partial[("chelsea", "headed_contacts")]["available"] is False
    full = stats(actions, match={"homeContestantId": "chelsea", "capabilities": json.dumps({"bodyParts": True})})
    assert (value(full, "chelsea", "headed_passes"), value(full, "chelsea", "headed_shots"),
            value(full, "chelsea", "headed_contacts")) == (1, 1, 3)


def test_snapshots_count_final_actions_only():
    actions = [action("pass", seq=1, final=1), action("pass", seq=2, final=4), action("shot", seq=3, final=3)]
    assert value(stats(actions, seq=3), "chelsea", "passes") == 1
    assert value(stats(actions, seq=3), "chelsea", "shots") == 1
    assert value(stats(actions, seq=4), "chelsea", "passes") == 2


def test_cards_come_from_ma3_rows_up_to_the_snapshot():
    raw = [{"typeId": 17, "contestantId": "manutd", "eventSeq": 2}, {"typeId": 17, "contestantId": "chelsea", "eventSeq": 9},
           {"typeId": 4, "contestantId": "chelsea", "eventSeq": 1},
           {"typeId": 17, "contestantId": "chelsea", "payload": json.dumps({"eventSeq": 3})}]
    s = stats([], raw, seq=5)
    assert (value(s, "chelsea", "cards"), value(s, "manutd", "cards"), value(s, "all", "cards")) == (1, 1, 2)
    assert s[("all", "cards")]["eventTypes"] == "[]"


def test_retired_kinds_are_served_unavailable():
    s = stats([action("pass")])
    for kind in ("kick_offs", "ball_recoveries", "aerials_won"):
        assert s[("all", kind)]["available"] is False and s[("all", kind)]["value"] is None
