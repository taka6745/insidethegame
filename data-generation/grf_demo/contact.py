"""Meanings of executed native contacts, separate from provider event keys."""

RESTARTS = {1: "kick_off", 2: "goal_kick", 3: "free_kick", 4: "corner", 5: "throw_in", 6: "penalty"}


def body_part(row):
    if row["touch_type"] not in (0, 1):
        return None  # An incidental collision need not use the animation's touch limb.
    if row["function"] == 7:
        return "head"
    name = row.get("touch_body_part", "")
    if "head" in name:
        return "head"
    if "foot" in name:
        return "left_foot" if "left" in name else "right_foot" if "right" in name else "foot"
    if "hand" in name:
        return "hand"
    return "other" if name else None


def action_function(row):
    # A header is an animation; intent distinguishes headed distribution and attempt.
    function = row["function"]
    if function == 7 and row.get("requested_function") in (4, 5, 6, 8):
        return row["requested_function"]
    return function


def contact_qualifiers(row):
    part = body_part(row)
    result = [{"type": "bodyPart", "value": part}] if part else []
    if row.get("event_restart"):
        result.append({"type": "restart", "value": row["event_restart"]})
    return result
