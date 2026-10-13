"""A 90-minute physics match; used with match_duration=4.75 (one-to-one clock)."""

from importlib import import_module


def build_scenario(builder):
    import_module("gfootball.scenarios.11_vs_11_stochastic").build_scenario(builder)
    # Safety ceiling only; the renderer stops at 5,400,000 match-clock ms.
    builder.config().game_duration = 200_000
    # Upstream referee expresses this threshold in legacy 1,800-ms units.
    builder.config().second_half = 1500  # 45 minutes, independent of render FPS.
