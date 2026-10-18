"""Patch a disposable GRF source copy, never the installed or archived runtime."""

import argparse
from pathlib import Path
import json
import unicodedata
from .roster import NAMES


def prepare(source):
    cpp = source / "third_party/gfootball_engine/src/data/playerdata.cpp"
    text = cpp.read_text()
    marker = "  // get average stat for current age"
    if marker not in text or "demoNames" in text:
        raise ValueError("Expected an unmodified pinned playerdata.cpp")
    ids = [398, 11, 254, 320, 103, 188, 74, 332, 290, 391, 264]
    names = [
        [
            unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
            for name in team
        ]
        for team in NAMES
    ]
    rows = ",\n".join(
        "    {" + ",".join(json.dumps(name) for name in team) + "}" for team in names
    )
    code = f"""  // Presentation-only names; generic simulator abilities are unchanged.
  const int demoIds[] = {{{",".join(map(str, ids))}}};
  const char* demoNames[2][11] = {{\n{rows}\n  }};
  for (int i=0; i<11; ++i) {{
    if (playerDatabaseID == demoIds[i]) lastName = demoNames[left_team ? 0 : 1][i];
  }}

"""
    cpp.write_text(text.replace(marker, code + marker))
    team = source / "third_party/gfootball_engine/src/data/teamdata.cpp"
    team.write_text(
        team.read_text()
        .replace("Frequentists United", "Chelsea")
        .replace("Real Bayesians", "Manchester United")
        .replace('"FRQ"', '"CHE"')
        .replace('"RBA"', '"MUN"')
    )
    import cv2

    kits = (
        source
        / "third_party/gfootball_engine/data/databases/default/images_teams/primeradivision"
    )
    for name, hue in [("fcbarcelona", 110), ("realmadrid", 0)]:
        path = kits / f"{name}_kit_02.bmp"
        image = cv2.imread(str(path))
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturated = hsv[:, :, 1] > 70
        hsv[:, :, 0][saturated] = hue
        hsv[:, :, 1][saturated] = 225
        cv2.imwrite(str(path), cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source)
