"""Per-team runtime tactic knobs in a disposable, pinned native GRF source.

Adds `set_tactic(team, name, value)` to the engine module. The capture's policy layer
(tactics.py) sets the knobs from the fixture's script; defaults keep upstream behaviour.

- press: 0..1 (0.5 upstream). How far, and how many, players hunt the ball carrier.
- line: -0.5..0.5 (0). Block height and attacking intent; also feeds the native offensiveness.
- flank: -1..1 (0). In possession, shift shape and pass choice to the right (+) or left (-) wing.
- direct: 0..1 (0). Pass choice favours forward progress over keeping the ball.
- energy: 0..1 (1). Off-ball running speed and pressing range; models fatigue.
- form: 0..1 (1). Scales outfield players' abilities, like the native fatigue factor; keepers unchanged.
"""

import argparse
from pathlib import Path

from .prepare_presentation import replace_once

KNOBS = ("press", "line", "flank", "direct", "energy", "form")
DEFAULTS = {"press": 0.5, "line": 0.0, "flank": 0.0, "direct": 0.0, "energy": 1.0, "form": 1.0}

HEADER = """// ITG tactics: per-team runtime knobs, set from Python via set_tactic (grf_demo/prepare_tactics.py).
#pragma once
#include <string>

enum GrfTacticKnob { kGrfPress, kGrfLine, kGrfFlank, kGrfDirect, kGrfEnergy, kGrfForm, kGrfKnobCount };

inline float *GrfTacticTable() {
  static float table[2 * kGrfKnobCount] = {%(defaults)s, %(defaults)s};
  return table;
}

inline float GrfTactic(int team, GrfTacticKnob knob) {
  return GrfTacticTable()[(team ? 1 : 0) * kGrfKnobCount + knob];
}

inline bool GrfSetTactic(int team, const std::string &name, float value) {
  static const char *names[kGrfKnobCount] = {%(names)s};
  for (int i = 0; i < kGrfKnobCount; i++) {
    if (name == names[i] && (team == 0 || team == 1)) {
      GrfTacticTable()[team * kGrfKnobCount + i] = value;
      return true;
    }
  }
  return false;
}
""" % {"defaults": ", ".join(f"{DEFAULTS[k]}f" for k in KNOBS), "names": ", ".join(f'"{k}"' for k in KNOBS)}


def prepare(source):
    engine = source / "third_party/gfootball_engine"
    src = engine / "src"
    (src / "onthepitch/grf_tactics.hpp").write_text(HEADER)
    replace_once(engine / "ai.cpp", '#include "src/game_env.hpp"\n',
                 '#include "src/game_env.hpp"\n#include "src/onthepitch/grf_tactics.hpp"\n')
    replace_once(engine / "ai.cpp", "BOOST_PYTHON_MODULE(_gameplayfootball) {\n",
                 "BOOST_PYTHON_MODULE(_gameplayfootball) {\n  def(\"set_tactic\", &GrfSetTactic);\n")

    team = src / "onthepitch/teamAIcontroller.cpp"
    replace_once(team, '#include "teamAIcontroller.hpp"\n', '#include "teamAIcontroller.hpp"\n#include "grf_tactics.hpp"\n')
    # line raises the native offensiveness (line height, support, side focus).
    replace_once(
        team,
        "  offensivenessBias = offenseBias * 0.5f + recentPossessionBias * 0.5f;\n",
        "  offensivenessBias = offenseBias * 0.5f + recentPossessionBias * 0.5f;\n"
        "  offensivenessBias = clamp(offensivenessBias + GrfTactic(team->GetID(), kGrfLine), 0.0f, 1.0f);\n",
    )
    # line moves the whole block up (+) or down (-) the pitch.
    replace_once(
        team,
        "       (defense_ownHalfFactor * 2.0f - 1.0f) * (1.0f - possessionBias));\n",
        "       (defense_ownHalfFactor * 2.0f - 1.0f) * (1.0f - possessionBias));\n"
        "  offsetX -= pitchHalfW * team->GetDynamicSide() * GrfTactic(team->GetID(), kGrfLine) * 0.35f;\n",
    )
    # flank shifts the shape towards one wing while in possession.
    replace_once(
        team,
        "  float centerY = clamp(ballY, -pitchHalfH, pitchHalfH);\n",
        "  float centerY = clamp(ballY + GrfTactic(team->GetID(), kGrfFlank) * team->GetDynamicSide() *\n"
        "      pitchHalfH * 0.6f * possessionBias, -pitchHalfH, pitchHalfH);\n",
    )
    # More attacking runs when pushing up.
    replace_once(
        team,
        "        float neededRating = 0.5f;\n",
        "        float neededRating = 0.5f - GrfTactic(team->GetID(), kGrfLine) * 0.3f;\n",
    )

    ai = src / "onthepitch/player/controller/elizacontroller.cpp"
    replace_once(ai, '#include "elizacontroller.hpp"\n', '#include "elizacontroller.hpp"\n#include "../../grf_tactics.hpp"\n')
    # Pressing range: wider for a high press, and a low block lets a deep opponent have the ball.
    replace_once(
        ai,
        "          0.3f + CastPlayer()->GetTeam()->GetAiDifficulty() * 0.7f;\n",
        "          0.3f + CastPlayer()->GetTeam()->GetAiDifficulty() * 0.7f;\n"
        "      float press = GrfTactic(team->GetID(), kGrfPress);\n"
        "      huntDistanceThreshold *= (0.4f + 1.2f * press) * GrfTactic(team->GetID(), kGrfEnergy);\n"
        "      if (opp->GetPosition().coords[0] * team->GetDynamicSide() < -10.0f)\n"
        "        huntDistanceThreshold *= 0.5f + press;  // opponent deep in their own half\n",
    )
    replace_once(
        ai,
        "            2;  // remember, this includes players with man marking id that are\n",
        "            GrfTactic(team->GetID(), kGrfPress) > 0.75f ? 3 : 2;  // remember, this includes players with man marking id that are\n",
    )
    replace_once(
        ai,
        "  float forwardWeight = 2.0f + AI_GetMindSet(CastPlayer()->GetDynamicFormationEntry().role) * 6.0f;\n",
        "  float forwardWeight = 2.0f + AI_GetMindSet(CastPlayer()->GetDynamicFormationEntry().role) * 6.0f +\n"
        "      GrfTactic(team->GetID(), kGrfDirect) * 6.0f;\n",
    )
    replace_once(
        ai,
        "      if (mates[i]->GetFormationEntry().role == e_PlayerRole_GK) mateTacticalRating *= 0.7f; // don't like playing back to goalie\n",
        "      if (mates[i]->GetFormationEntry().role == e_PlayerRole_GK) mateTacticalRating *= 0.7f; // don't like playing back to goalie\n"
        "      mateTacticalRating += GrfTactic(team->GetID(), kGrfFlank) * 0.05f *\n"
        "          clamp(mates[i]->GetPosition().coords[1] * team->GetDynamicSide() / pitchHalfH, -1.0f, 1.0f);\n",
    )
    # form scales outfield abilities, as the native fatigue factor does.
    player = src / "onthepitch/player/player.cpp"
    replace_once(player, '#include "player.hpp"\n', '#include "player.hpp"\n#include "../grf_tactics.hpp"\n')
    replace_once(
        player,
        "  float multiplier = 0.3f + 0.7f * team->GetAiDifficulty();\n",
        "  float multiplier = 0.3f + 0.7f * team->GetAiDifficulty();\n"
        "  if (dynamicFormationEntry.role != e_PlayerRole_GK) multiplier *= GrfTactic(team->GetID(), kGrfForm);\n",
    )
    # Fatigue: tired teams run less off the ball.
    replace_once(
        ai,
        "  resultingVelocityFloat = std::min(resultingVelocityFloat, sprintVelocity * breathLeftFactor);\n",
        "  resultingVelocityFloat = std::min(resultingVelocityFloat, sprintVelocity * breathLeftFactor);\n"
        "  resultingVelocityFloat *= 0.55f + 0.45f * GrfTactic(team->GetID(), kGrfEnergy);\n",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source)
