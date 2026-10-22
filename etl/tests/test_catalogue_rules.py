"""Counting rules of the SPADL stat catalogue on small synthetic actions.

Own goals and fouls count for the other team; shots on target and blocked shots read the source Opta type and
the goal line; entries cross zones relative to the acting team; capabilities decide availability; snapshots
read only actions final at their seq; cards and VAR overturns come from MA3 rows bounded by eventSeq.
"""
import json

from reference import catalogue

TEAMS = [{"contestantId": "riverton", "name": "Riverton Rovers", "position": "home"},
         {"contestantId": "forgeham", "name": "Forgeham United", "position": "away"}]
MATCH = {"homeContestantId": "riverton", "capabilities": json.dumps({"shotOutcomes": True})}


def action(type_name, seq=1, team="riverton", result="success", body="foot", end_x=50.0, source_type=1,
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
               action("bad_touch", team="forgeham", result="owngoal"), action("shot", team="forgeham")])
    assert (value(s, "riverton", "goals"), value(s, "forgeham", "goals"), value(s, "all", "goals")) == (3, 1, 4)
    assert (value(s, "riverton", "shots"), value(s, "riverton", "penalties")) == (3, 1)


def var(seq, team, own_goal=False, outcome="goal-overturned"):
    """An MA3 VAR decision (type 900, qualifier 901) as rawEvents stores it."""
    qualifier = [{"qualifierId": 901, "value": outcome}] + ([{"qualifierId": 28}] if own_goal else [])
    return {"typeId": 900, "contestantId": team, "payload": json.dumps({"eventSeq": seq, "qualifier": qualifier})}


VAR_ACTIONS = [action("shot", seq=1), action("bad_touch", seq=2, team="forgeham", result="owngoal"), action("shot", seq=3),
               action("shot", seq=4, team="forgeham")]
VAR_ROWS = [var(5, "riverton"), var(6, "forgeham", own_goal=True), var(7, "riverton", outcome="goal-confirmed"),
            var(8, "forgeham")]


def test_var_overturns_take_goals_back_from_their_seq():
    goals = lambda seq: tuple(value(stats(VAR_ACTIONS, VAR_ROWS, seq=seq), t, "goals") for t in ("riverton", "forgeham", "all"))
    assert goals(4) == (3, 1, 4)  # two goals and an own goal for Riverton Rovers
    assert goals(5) == (2, 1, 3)  # Riverton Rovers' goal overturned
    assert goals(6) == (1, 1, 2)  # United's own goal overturned: Riverton Rovers lose it
    assert goals(7) == (1, 1, 2)  # a confirmed goal changes nothing
    assert goals(8) == (1, 0, 1)
    assert value(stats(VAR_ACTIONS, VAR_ROWS, seq=8), "riverton", "shots") == 2  # the attempts stay


def test_fouls_won_are_the_opponents_fouls():
    s = stats([action("foul", result="fail"), action("foul", team="forgeham", result="fail"),
               action("foul", team="forgeham", result="fail")])
    assert (value(s, "riverton", "fouls"), value(s, "riverton", "fouls_won")) == (1, 2)
    assert (value(s, "forgeham", "fouls_won"), value(s, "all", "fouls_won"), value(s, "all", "fouls")) == (1, 3, 3)


def test_pass_family_set_pieces_and_offsides():
    kinds = ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"]
    s = stats([action(k) for k in kinds] + [action("pass", result="offside"), action("cross", result="fail"),
                                            action("shot_freekick", result="fail")])
    assert (value(s, "riverton", "passes"), value(s, "riverton", "passes_completed"), value(s, "riverton", "offsides")) == (10, 8, 1)
    assert value(s, "riverton", "pass_accuracy") == 80.0
    assert (value(s, "riverton", "crosses"), value(s, "riverton", "crosses_completed"), value(s, "riverton", "cross_accuracy")) == (4, 3, 75.0)
    assert (value(s, "riverton", "corners"), value(s, "riverton", "free_kicks"), value(s, "riverton", "free_kick_shots")) == (2, 3, 1)
    assert (value(s, "riverton", "throw_ins"), value(s, "riverton", "goal_kicks")) == (1, 1)


def test_accuracy_is_unavailable_without_attempts():
    s = stats([action("shot")])
    assert s[("riverton", "pass_accuracy")]["available"] is False and value(s, "riverton", "pass_accuracy") is None


def test_on_target_and_blocked_read_the_goal_line_in_the_teams_frame():
    s = stats([action("shot", result="success", source_type=16),
               action("shot", result="fail", source_type=15, end_x=105.0),   # saved
               action("shot", result="fail", source_type=15, end_x=90.0),    # blocked
               action("shot", result="fail", source_type=13, end_x=105.0),   # missed
               action("shot", team="forgeham", result="fail", source_type=15, end_x=0.0),   # away: saved
               action("shot", team="forgeham", result="fail", source_type=15, end_x=12.0)])
    assert (value(s, "riverton", "shots_on_target"), value(s, "riverton", "blocked_shots")) == (2, 1)
    assert (value(s, "forgeham", "shots_on_target"), value(s, "forgeham", "blocked_shots")) == (1, 1)
    no_outcomes = stats([action("shot")], match={"homeContestantId": "riverton",
                                                 "capabilities": json.dumps({"shotOutcomes": False})})
    assert no_outcomes[("riverton", "shots_on_target")]["available"] is False


def test_entries_cross_into_the_zone():
    s = stats([action("pass", start_zone="middle_third", end_zone="final_third"),
               action("cross", start_zone="final_third", end_zone="opp_box"),
               action("dribble", start_zone="middle_third", end_zone="opp_box"),
               action("pass", start_zone="final_third", end_zone="final_third"),
               action("pass", result="fail", start_zone="middle_third", end_zone="opp_box"),
               action("take_on", start_zone="middle_third", end_zone="final_third")])
    assert (value(s, "riverton", "final_third_entries"), value(s, "riverton", "box_entries")) == (2, 2)


def test_headed_stats_follow_body_part_coverage():
    actions = [action("pass", body="head"), action("shot", body="head"), action("clearance", body="head"),
               action("pass", body="foot_left")]
    passes = ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short",
              "goalkick"]
    partial = stats(actions, match={"homeContestantId": "riverton", "capabilities": json.dumps(
        {"bodyParts": False, "bodyPartEventTypes": ["pass"], "bodyPartActionTypes": passes + ["shot"]})})
    assert value(partial, "riverton", "headed_passes") == 1
    assert partial[("riverton", "headed_shots")]["available"] is False  # shot_penalty, shot_freekick uncertified
    provider_only = stats(actions, match={"homeContestantId": "riverton", "capabilities": json.dumps(
        {"bodyParts": False, "bodyPartEventTypes": ["pass", "shot", "goal"]})})  # SPADL coverage is what counts
    assert provider_only[("riverton", "headed_passes")]["available"] is False
    assert partial[("riverton", "headed_contacts")]["available"] is False
    full = stats(actions, match={"homeContestantId": "riverton", "capabilities": json.dumps({"bodyParts": True})})
    assert (value(full, "riverton", "headed_passes"), value(full, "riverton", "headed_shots"),
            value(full, "riverton", "headed_contacts")) == (1, 1, 3)


def test_snapshots_count_final_actions_only():
    actions = [action("pass", seq=1, final=1), action("pass", seq=2, final=4), action("shot", seq=3, final=3)]
    assert value(stats(actions, seq=3), "riverton", "passes") == 1
    assert value(stats(actions, seq=3), "riverton", "shots") == 1
    assert value(stats(actions, seq=4), "riverton", "passes") == 2


def test_cards_come_from_ma3_rows_up_to_the_snapshot():
    raw = [{"typeId": 17, "contestantId": "forgeham", "eventSeq": 2}, {"typeId": 17, "contestantId": "riverton", "eventSeq": 9},
           {"typeId": 4, "contestantId": "riverton", "eventSeq": 1},
           {"typeId": 17, "contestantId": "riverton", "payload": json.dumps({"eventSeq": 3})}]
    s = stats([], raw, seq=5)
    assert (value(s, "riverton", "cards"), value(s, "forgeham", "cards"), value(s, "all", "cards")) == (1, 1, 2)
    assert s[("all", "cards")]["eventTypes"] == "[]"


def test_retired_kinds_are_served_unavailable():
    s = stats([action("pass")])
    for kind in ("kick_offs", "ball_recoveries", "aerials_won"):
        assert s[("all", kind)]["available"] is False and s[("all", kind)]["value"] is None
