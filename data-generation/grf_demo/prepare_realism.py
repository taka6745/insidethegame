"""Runtime realism knobs in a disposable, pinned native GRF source.

Each knob is read from the environment; unset values keep upstream behaviour.
The capture sets them from scenario.REALISM and records them in provenance.
"""

import argparse
from pathlib import Path

from .prepare_presentation import replace_once

KNOB = """
#include <cstdlib>
#include <string>
#include <unordered_map>
static float GrfKnob(const char *name, float fallback) {
  // Read once per process; knobs are called from per-player and per-animation loops.
  static std::unordered_map<std::string, float> cache;
  auto found = cache.find(name);
  if (found != cache.end()) return found->second;
  const char *value = std::getenv(name);
  return cache[name] = value ? std::atof(value) : fallback;
}
"""


def prepare(source):
    src = source / "third_party/gfootball_engine/src"
    player = src / "data/playerdata.cpp"
    replace_once(player, '#include "../main.hpp"\n', '#include "../main.hpp"\n' + KNOB)
    # Lift every stat towards 1.0; profile 398 is the goalkeeper slot.
    replace_once(
        player,
        "    stats.Set(PlayerStatFromString((*iter).first), value);",
        "    float skill = GrfKnob(playerDatabaseID == 398 ? \"GRF_KEEPER_SKILL\" : \"GRF_SKILL\", 0.0f);\n"
        "    value = value + (1.0f - value) * skill;\n"
        "    stats.Set(PlayerStatFromString((*iter).first), value);",
    )
    ai = src / "onthepitch/player/controller/elizacontroller.cpp"
    replace_once(ai, '#include "elizacontroller.hpp"\n', '#include "elizacontroller.hpp"\n' + KNOB)
    # Fewer speculative attempts.
    replace_once(
        ai,
        "if (odds + boostrandom(0.0f, 0.5f) > 0.5f) {",
        "if (odds + boostrandom(0.0f, 0.5f) > GrfKnob(\"GRF_SHOT_THRESHOLD\", 0.5f)) {",
    )
    # Panic clearances may otherwise become speculative shots.
    replace_once(
        ai,
        "  command.desiredFunctionType = e_FunctionType_Shot;\n  command.touchInfo.inputPower = 0.6f;\n  command.touchInfo.desiredPower = 0.6f;\n  commandQueue.push_back(command);",
        "  command.desiredFunctionType = e_FunctionType_Shot;\n  command.touchInfo.inputPower = 0.6f;\n  command.touchInfo.desiredPower = 0.6f;\n"
        "  if (GrfKnob(\"GRF_PANIC_SHOT\", 1.0f) > 0.5f) commandQueue.push_back(command);",
    )
    # Upstream shots leave too fast for the keeper's save animations.
    replace_once(
        ai,
        "      command.touchInfo.desiredPower = boostrandom(\n          0.7f * (0.6f + goalDist * 0.4f), 1.0f * (0.6f + goalDist * 0.4f));",
        "      command.touchInfo.desiredPower = GrfKnob(\"GRF_SHOT_POWER\", 1.0f) * boostrandom(\n          0.7f * (0.6f + goalDist * 0.4f), 1.0f * (0.6f + goalDist * 0.4f));",
    )
    aim = src / "onthepitch/AIsupport/AIfunctions.cpp"
    replace_once(aim, '#include "AIfunctions.hpp"\n', '#include "AIfunctions.hpp"\n' + KNOB)
    # Auto-aim otherwise places every attempt just inside a post. Error grows with distance.
    replace_once(
        aim,
        "      sideFactor * goalHalfWidth * 0.9f * player->GetTeam()->GetDynamicSide();",
        "      sideFactor * goalHalfWidth * 0.9f * player->GetTeam()->GetDynamicSide();\n"
        "  float scatter = GrfKnob(\"GRF_SHOT_SCATTER\", 0.0f);\n"
        "  if (scatter > 0.0f) goalPos.coords[1] += boostrandom(-scatter, scatter) * (1.2f - player->GetStat(technical_shot)) *\n"
        "      (0.5f + (goalPos - player->GetPosition()).GetLength() / 20.0f);",
    )
    goalie = src / "onthepitch/player/controller/strategies/offtheball/goalie_default.cpp"
    replace_once(goalie, '#include "goalie_default.hpp"\n', '#include "goalie_default.hpp"\n' + KNOB)
    # Upstream keepers rush to the shooting point and are beaten from 12 metres.
    replace_once(
        goalie,
        "      float distance = std::max(ballToGoal.GetLength() - 0.5f, 0.0f);",
        "      awayFromGoalBias = std::min(awayFromGoalBias, GrfKnob(\"GRF_KEEPER_RUSH\", 1.0f));\n"
        "      float distance = std::max(ballToGoal.GetLength() - 0.5f, 0.0f);",
    )
    referee = src / "onthepitch/referee.cpp"
    replace_once(referee, '#include "referee.hpp"\n', '#include "referee.hpp"\n' + KNOB)
    # Upstream plays advantage on every standing foul and rarely whistles; matches end with ~3 fouls.
    replace_once(
        referee,
        "      foul.foulType = 1;\n      foul.advantage = true;",
        "      foul.foulType = 1;\n      float whistle = GrfKnob(\"GRF_STANDING_WHISTLE\", 0.0f);\n"
        "      // Unset keeps upstream: always advantage, and no extra random draw.\n"
        "      foul.advantage = !(whistle > 0.0f && boostrandom(0.0f, 1.0f) < whistle);",
    )
    replace_once(
        referee,
        "      severity += (tripee->GetPosition() - tripper->GetPosition()).GetNormalized(0).GetDotProduct(tripee->GetDirectionVec()) * 0.5 + 0.5;",
        "      severity += (tripee->GetPosition() - tripper->GetPosition()).GetNormalized(0).GetDotProduct(tripee->GetDirectionVec()) * 0.5 + 0.5;\n"
        "      severity += GrfKnob(\"GRF_FOUL_BIAS\", 0.0f);",
    )
    # Upstream ignores contact trips (type 1), the source of most real fouls.
    replace_once(
        referee,
        "  if (buffer.active) return;\n\n  if (tackleType == 2) {",
        "  if (buffer.active) return;\n\n"
        "  Vector3 tripPos = tripee->GetPitchPosition();\n"
        "  bool inBox = fabs(tripPos.coords[1]) < 20.15 - lineHalfW &&\n"
        "      tripPos.coords[0] * -tripee->GetTeam()->GetStaticSide() > pitchHalfW - 16.5 + lineHalfW;\n"
        "  float boxFoul = GrfKnob(\"GRF_BOX_FOUL\", 1.0f);\n"
        "  // Defenders are more careful in their own box; most box contact is waved on.\n"
        "  if (inBox && boxFoul < 1.0f && boostrandom(0.0f, 1.0f) >= boxFoul) return;\n"
        "  float contactFoul = GrfKnob(\"GRF_CONTACT_FOUL\", 0.0f);\n"
        "  if (tackleType == 1 && contactFoul > 0.0f && foul.foulType == 0 &&\n"
        "      tripper->GetTeam()->GetID() != tripee->GetTeam()->GetID() &&\n"
        "      (tripee->GetPosition() - match->GetBall()->Predict(0).Get2D()).GetLength() < 2.0 &&\n"
        "      boostrandom(0.0f, 1.0f) < contactFoul) {\n"
        "    foul.foulType = boostrandom(0.0f, 1.0f) < GrfKnob(\"GRF_CONTACT_CARD\", 0.0f) ? 2 : 1;\n"
        "    foul.advantage = false;\n"
        "    foul.foulPlayer = tripper;\n"
        "    foul.foulVictim = tripee;\n"
        "    foul.foulTime = match->GetActualTime_ms();\n"
        "    foul.foulPosition = tripee->GetPitchPosition();\n"
        "    foul.hasBeenProcessed = false;\n"
        "    return;\n"
        "  }\n\n  if (tackleType == 2) {",
    )
    # Pass selection otherwise ignores the offside line.
    replace_once(
        ai,
        "      if (mateTacticalRating > tacticalRating + tacticalImprovementThreshold) {",
        "      float offsideRisk = GrfKnob(\"GRF_OFFSIDE_RISK\", 1.0f);\n"
        "      float attack = -team->GetDynamicSide();\n"
        "      float mateX = mates[i]->GetPosition().coords[0] * attack;\n"
        "      bool offside = offsideRisk < 1.0f && mateX > 0.0f &&\n"
        "          mateX > AI_GetOffsideLine(match, _mentalImage, abs(team->GetID() - 1), 0) * attack + 0.3f &&\n"
        "          mateX > match->GetBall()->Predict(0).coords[0] * attack &&\n"
        "          boostrandom(0.0f, 1.0f) >= offsideRisk;\n"
        "      if (!offside && mateTacticalRating > tacticalRating + tacticalImprovementThreshold) {",
    )
    # Attackers hold position 8 cm onside and drift offside with their run.
    replace_once(
        ai,
        "  float margin = 0.08f;\n  if (forceNoOffside)",
        "  float margin = GrfKnob(\"GRF_ONSIDE_MARGIN\", 0.08f);\n  if (forceNoOffside)",
    )
    humanoid = src / "onthepitch/player/humanoid/humanoid.cpp"
    replace_once(humanoid, '#include "humanoid.hpp"\n', '#include "humanoid.hpp"\n' + KNOB)
    # Finishing quality: some executed attempts are snatched off target.
    shot_touch = ("        match->GetBall()->Touch(touchVec);\n"
                  "        match->GetBall()->SetRotation(xRot, yRot, zRot, 0.7f * (1.0f - bumpyRideBias));\n")
    replace_once(
        humanoid,
        shot_touch,
        "        float mishit = GrfKnob(\"GRF_MISHIT\", 0.0f);\n"
        "        if (mishit > 0.0f && boostrandom(0.0f, 1.0f) < mishit) {\n"
        "          touchVec = touchVec.GetRotated2D((boostrandom(0.0f, 1.0f) < 0.5f ? -1.0f : 1.0f) * boostrandom(0.1f, 0.25f));\n"
        "          touchVec.coords[2] += boostrandom(0.0f, 2.0f);\n"
        "        }\n" + shot_touch,
    )
    # Deflect animations are goalkeeper saves; widen their reachable radius.
    replace_once(
        humanoid,
        "          radiusFactor *= 1.8f;\n          radiusCheatOffset += 0.4f;",
        "          radiusFactor *= 1.8f * GrfKnob(\"GRF_KEEPER_REACH\", 1.0f);\n"
        "          radiusCheatOffset += 0.4f * GrfKnob(\"GRF_KEEPER_REACH\", 1.0f);",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source)
