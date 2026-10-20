"""Add observational referee/contact facts to the pinned instrumented GRF copy."""

import argparse
from pathlib import Path


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Unexpected native source around {old[:70]!r}")
    return text.replace(old, new, 1)


def prepare(source):
    root = source / "third_party/gfootball_engine/src"
    paths = {name: root / name for name in ("game_env.hpp", "game_env.cpp", "onthepitch/referee.cpp")}
    original = {name: path.read_text() for name, path in paths.items()}
    if all("ITG telemetry v2" in text for text in original.values()):
        return
    if any("ITG telemetry v2" in text for text in original.values()):
        raise ValueError("Partially patched source; restore the disposable copy first")
    changed = dict(original)
    changed["game_env.hpp"] = replace(original["game_env.hpp"],
        "  void record_telemetry(Player* touched = nullptr, int touch_type = -1);",
        """  void record_telemetry(Player* touched = nullptr, int touch_type = -1);
  // ITG telemetry v2: observational facts, no simulation state changes.
  void record_decision(const char* kind, Player* actor, Player* related = nullptr, int card = 0);""")
    cpp = replace(original["game_env.cpp"], '#include "gametask.hpp"',
                  '#include "gametask.hpp"\n#include "onthepitch/referee.hpp"')
    cpp = replace(cpp, '  if (touched) {\n    o << ",\\\"player\\\":"; id(o, touched);', r'''  // ITG telemetry v2: buffer values are authoritative only while active.
  const auto& restart = match->GetReferee()->GetBuffer();
  o << ",\"telemetry_version\":2,\"restart_active\":" << (restart.active ? "true" : "false")
    << ",\"restart_mode\":" << (restart.active ? int(restart.desiredSetPiece) : 0)
    << ",\"restart_team\":" << (restart.active ? restart.teamID : -1)
    << ",\"restart_id\":" << (restart.active ? restart.stopTime : 0);
  o << ",\"ball_retainer\":"; id(o, match->GetBallRetainer());
  o << ",\"initial_kickoff_team\":" << (!match->GetLastTouchPlayer() &&
      match->GetMatchPhase() == e_MatchPhase_1stHalf && restart.desiredSetPiece == e_GameMode_KickOff && restart.setpiece_team
      ? restart.setpiece_team->GetID() : -1);
  if (touched) {
    auto body = touched->GetCurrentAnim()->anim->GetVariable("touch_bodypart");
    // Animation asset identifiers, restricted to JSON-safe characters.
    for (auto& c : body) if (!(c >= 'a' && c <= 'z') && c != '_') c = '_';
    o << ",\"touch_body_part\":\"" << body << "\"";
    o << ",\"player\":"; id(o, touched);''')
    cpp += r'''

void GameEnv::record_decision(const char* kind, Player* actor, Player* related, int card) {
  if (!telemetry_enabled) return;
  auto match = GetGameTask()->GetMatch();
  if (!match) return;
  auto id = [](std::ostream& out, Player* p) {
    if (!p) out << "null";
    else out << '[' << p->GetTeamID() << ',' << p->GetStableID() << ']';
  };
  std::ostringstream out;
  out << "{\"kind\":\"decision\",\"telemetry_version\":2,\"decision\":\"" << kind
      << "\",\"physics_ms\":" << match->GetActualTime_ms()
      << ",\"match_ms\":" << match->GetMatchTime_ms()
      << ",\"phase\":" << int(match->GetMatchPhase()) << ",\"player\":";
  id(out, actor);
  out << ",\"related_player\":"; id(out, related);
  const auto& restart = match->GetReferee()->GetBuffer();
  out << ",\"restart_team\":" << (restart.setpiece_team ? restart.setpiece_team->GetID() : -1);
  out << ",\"card\":" << card << '}';
  telemetry.push_back(out.str());
}
'''
    changed["game_env.cpp"] = cpp
    ref = replace(original["onthepitch/referee.cpp"], '#include "referee.hpp"',
                  '#include "referee.hpp"\n#include "../game_env.hpp"\n// ITG telemetry v2')
    ref = replace(ref, '          match->SpamMessage("offside!");',
                  '          GetGame()->record_decision("offside", ballOwner);\n          match->SpamMessage("offside!");')
    ref = replace(ref, '    std::string spamMessage = "foul!";',
                  '''    // Record the whistle, not tentative contact or an advantage that expires.
    int card = foul.foulType == 3 ? 3 : foul.foulType == 2 ? (foul.foulPlayer->HasCards() ? 2 : 1) : 0;
    GetGame()->record_decision("foul", foul.foulPlayer, foul.foulVictim, card);
    std::string spamMessage = "foul!";''')
    ref = replace(ref, '        match->StartSetPiece();',
                  '        match->StartSetPiece();\n        if (buffer.desiredSetPiece == e_GameMode_KickOff) GetGame()->record_decision("kick_off_ready", nullptr);')
    changed["onthepitch/referee.cpp"] = ref
    # Validate every anchor before modifying any file.
    for name, text in changed.items():
        paths[name].write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source)
