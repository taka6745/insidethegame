"""Opta codes and the ETL rules that read them.

Reference implementation of the key-event and minute-stat rules. The Stream
Analytics query must produce the same results; tests compare the two.
"""
import json
from pathlib import Path

CODES = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "opta-codes.json").read_text())

# Event types
PASS, FOUL, CORNER_AWARDED, TACKLE, INTERCEPTION, SAVE, CLEARANCE = 1, 4, 6, 7, 8, 10, 12
MISS, POST, ATTEMPT_SAVED, GOAL, CARD, PLAYER_OFF, PLAYER_ON = 13, 14, 15, 16, 17, 18, 19
END, START, BALL_RECOVERY, VAR_DECISION = 30, 32, 49, 900

# Qualifiers
Q_CROSS, Q_FREE_KICK, Q_CORNER, Q_PENALTY, Q_OWN_GOAL = 2, 5, 6, 9, 28
Q_YELLOW, Q_SECOND_YELLOW, Q_RED, Q_RELATED_EVENT, Q_BLOCKED = 31, 32, 33, 55, 82
Q_GOAL_KICK, Q_END_X, Q_END_Y, Q_KICK_OFF, Q_VAR_OUTCOME = 124, 140, 141, 279, 901

SHOTS = {MISS, POST, ATTEMPT_SAVED, GOAL}

# Opta match-clock minute at which each period starts, and its regulation end.
PERIOD_START_MIN = {1: 0, 2: 45, 3: 90, 4: 105, 5: 120}
PERIOD_END_MIN = {1: 45, 2: 90, 3: 105, 4: 120, 5: 120}

STAT_COLUMNS = [
    "passes", "passesCompleted", "shots", "shotsOnTarget", "goals", "ownGoals",
    "corners", "fouls", "yellowCards", "redCards", "events",
]


def has_q(event, qualifier_id):
    return any(q["qualifierId"] == qualifier_id for q in event.get("qualifier", []))


def q_value(event, qualifier_id):
    return next((q.get("value") for q in event.get("qualifier", []) if q["qualifierId"] == qualifier_id), None)


def key_event(event):
    """Return (keyType, detail) for a narrative key event, else None."""
    t = event["typeId"]
    if t == GOAL:
        if has_q(event, Q_OWN_GOAL):
            return "OwnGoal", None
        return "Goal", "penalty" if has_q(event, Q_PENALTY) else None
    if t in (MISS, POST, ATTEMPT_SAVED) and has_q(event, Q_PENALTY):
        return "PenaltyMissed", None
    if t == FOUL and event["outcome"] == 0 and has_q(event, Q_PENALTY):
        return "PenaltyAwarded", "conceded"
    if t == CARD and has_q(event, Q_SECOND_YELLOW):
        return "RedCard", "second-yellow"
    if t == CARD and has_q(event, Q_RED):
        return "RedCard", None
    if t == VAR_DECISION and q_value(event, Q_VAR_OUTCOME) == "goal-overturned":
        return "VarOverturn", "own-goal-overturned" if has_q(event, Q_OWN_GOAL) else "goal-overturned"
    return None


def period_change(event):
    """Return PeriodStarted/PeriodEnded for period boundary events, else None."""
    return {START: "PeriodStarted", END: "PeriodEnded"}.get(event["typeId"])


def stat_deltas(event):
    """Per-contestant stat deltas contributed by one event.

    Own goals count against the contestant that scored them (ownGoals); the
    matchStatsAsOf view credits them to the opponent. VAR goal overturns
    subtract from the same column the goal was counted in.
    """
    t, own_goal = event["typeId"], has_q(event, Q_OWN_GOAL)
    var_overturn = t == VAR_DECISION and q_value(event, Q_VAR_OUTCOME) == "goal-overturned"
    return {
        "passes": int(t == PASS),
        "passesCompleted": int(t == PASS and event["outcome"] == 1),
        "shots": int(t in SHOTS and not own_goal),
        "shotsOnTarget": int((t == GOAL and not own_goal) or (t == ATTEMPT_SAVED and not has_q(event, Q_BLOCKED))),
        "goals": int(t == GOAL and not own_goal) - int(var_overturn and not own_goal),
        "ownGoals": int(t == GOAL and own_goal) - int(var_overturn and own_goal),
        "corners": int(t == CORNER_AWARDED and event["outcome"] == 1),
        "fouls": int(t == FOUL and event["outcome"] == 0),
        "yellowCards": int(t == CARD and has_q(event, Q_YELLOW)),
        "redCards": int(t == CARD and (has_q(event, Q_SECOND_YELLOW) or has_q(event, Q_RED))),
        "events": 1,
    }


def minute_label(period_id, time_min):
    """Broadcast-style minute: 0:30 -> "1'", 45:30 in period 1 -> "45+1'"."""
    shown, end = time_min + 1, PERIOD_END_MIN[period_id]
    return f"{end}+{shown - end}'" if shown > end else f"{shown}'"
