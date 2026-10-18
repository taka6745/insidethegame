"""Feed promises are grounded in instrumentation, not which events happened to occur."""

BASE_EVENTS = ["touch", "pass", "shot", "goal"]
NATIVE_V2_EVENTS = ["corner", "throw_in", "free_kick", "goal_kick", "kick_off", "penalty",
                    "offside", "foul", "foul_won", "card", "keeper_claim", "period_start", "period_end"]


def capabilities(version):
    result = {
        "supported_event_types": BASE_EVENTS + (NATIVE_V2_EVENTS if version >= 2 else []),
        "shot_outcomes": False,
        "distance_event_types": ["pass"],
        "body_parts": False,
        "shots_include_scoring_attempts": False,
        "possession_basis": "confirmed_native_ownership",
    }
    if version >= 2:
        result.update(restart_events="taken", body_part_event_types=["pass", "shot"])
    return result
