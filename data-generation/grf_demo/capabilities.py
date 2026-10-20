"""Feed promises are grounded in instrumentation, not which events happened to occur."""

BASE_EVENTS = ["touch", "pass", "shot", "goal"]
NATIVE_V2_EVENTS = ["corner", "throw_in", "free_kick", "goal_kick", "kick_off", "penalty",
                    "offside", "foul", "foul_won", "card", "keeper_claim", "period_start", "period_end"]
# Opta-style events derived from native tracking by documented rules (docs/opta-events.md).
DERIVED_EVENTS = ["save", "tackle", "dispossessed", "interception", "blocked_pass", "clearance",
                  "aerial", "take_on", "challenge", "ball_recovery", "out", "corner_awarded",
                  "keeper_pickup", "punch", "offside_provoked", "error", "ball_touch"]


def capabilities(version):
    result = {
        "supported_event_types": BASE_EVENTS + (NATIVE_V2_EVENTS + DERIVED_EVENTS if version >= 2 else []),
        "shot_outcomes": version >= 2,
        "distance_event_types": ["pass", "clearance"] if version >= 2 else ["pass"],
        "body_parts": False,
        "shots_include_scoring_attempts": False,
        "possession_basis": "confirmed_native_ownership",
    }
    if version >= 2:
        result.update(restart_events="taken", body_part_event_types=["pass", "shot"],
                      coordinates="opta_0_100", clock="broadcast_with_stoppage")
    return result
