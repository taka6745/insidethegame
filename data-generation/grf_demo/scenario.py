"""Equal built-in AIs; the capture sets active physics seconds per half."""

from importlib import import_module
import os

# Runtime knobs read by the prepare_realism engine patch. Tuned headless over full matches
# towards Premier League norms (about 26 shots, 3 goals, 21 fouls and 4 offsides per match).
# Each rendered match reports its own totals (data-generation/recordings/README.md).
REALISM = {
    "GRF_SKILL": 0.4,  # Lift every outfield stat 40% of the way to 1.0.
    "GRF_KEEPER_SKILL": 1.0,
    "GRF_KEEPER_REACH": 2.5,  # Save animations reach 2.5 times as far.
    "GRF_KEEPER_RUSH": 0.25,  # Keepers hold their line instead of rushing the shooter.
    "GRF_SHOT_THRESHOLD": 1.33,  # Shoot only from good chances (1.31 before scripted tactics).
    "GRF_PANIC_SHOT": 0,  # Clearances under pressure are not attempts.
    "GRF_SHOT_SCATTER": 8,  # Aim error in metres at 20 m, scaled by shooting skill.
    "GRF_SHOT_POWER": 0.4,  # Upstream strikes are too fast for any save animation.
    "GRF_MISHIT": 1.0,  # Every executed attempt deviates 6-14 degrees.
    "GRF_ONSIDE_MARGIN": 2.0,  # Attackers hold 2 m onside.
    "GRF_OFFSIDE_RISK": 0.1,  # One in ten passes to an offside teammate is still played.
    "GRF_CONTACT_FOUL": 0.03,  # Contact trips near the ball are whistled.
    "GRF_CONTACT_CARD": 0.12,
    "GRF_STANDING_WHISTLE": 0.1,
    "GRF_BOX_FOUL": 0.06,  # Most box contact is waved on.
    "GRF_FOUL_BIAS": 0.0,  # Recorded so provenance lists every knob.
}


def build_scenario(builder):
    import_module("gfootball.scenarios.11_vs_11_stochastic").build_scenario(builder)
    config = builder.config()
    config.left_team_difficulty = 1.0
    config.right_team_difficulty = 1.0
    config.game_duration = 100_000
    # Engine uses 1,800 ms units; 45 minutes of active play is 1,500.
    config.second_half = int(os.environ.get("GRF_HALF_SECONDS", "2700")) * 1000 // 1800
