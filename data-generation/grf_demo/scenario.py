"""Equal built-in AIs; six minutes of active physics per half."""

from importlib import import_module


def build_scenario(builder):
    import_module("gfootball.scenarios.11_vs_11_stochastic").build_scenario(builder)
    config = builder.config()
    config.left_team_difficulty = 1.0
    config.right_team_difficulty = 1.0
    config.game_duration = 100_000
    config.second_half = 200  # Engine uses 1,800 ms units: 360 physical seconds.
