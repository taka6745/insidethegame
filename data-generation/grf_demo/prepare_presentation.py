"""Reproducible presentation changes in a disposable, pinned native GRF source."""

import argparse
from pathlib import Path

from .roster import SHIRT_NUMBERS


def replace_once(path, original, replacement):
    text = path.read_text()
    if replacement in text:
        return
    if text.count(original) != 1:
        raise ValueError(f"Unexpected pinned source in {path.name}")
    path.write_text(text.replace(original, replacement))


def numbered_kit(image, number):
    """Paint the back UV island; the native mesh carries it through animation."""
    import cv2

    if image is None or image.shape != (1024, 1024, 3):
        raise ValueError("Expected pinned 1024px kit texture")
    result = image.copy()
    # The second torso island is the back (x620..915, y0..420). Remove the
    # generic back logo, retaining the sleeves, shorts and texture silhouette.
    result[90:405, 625:910] = image[300, 650]
    label = str(number)
    font, scale, thickness = cv2.FONT_HERSHEY_DUPLEX, 5.5, 10
    (width, height), _ = cv2.getTextSize(label, font, scale, thickness)
    origin = (768 - width // 2, 250 + height // 2)
    cv2.putText(result, label, origin, font, scale, (20, 20, 20), thickness + 6, cv2.LINE_AA)
    cv2.putText(result, label, origin, font, scale, (250, 250, 250), thickness, cv2.LINE_AA)
    return result


def prepare(source):
    import cv2

    engine = source / "third_party/gfootball_engine"
    replace_once(
        engine / "src/onthepitch/match.cpp",
        "  radar->Show();",
        "  radar->Hide();  // Recorded broadcast: no minimap overlay.",
    )
    replace_once(
        engine / "src/onthepitch/match.cpp",
        "  radar->Put();",
        "  // Hidden broadcast radar has no per-frame updates.",
    )
    replace_once(
        engine / "src/onthepitch/team.cpp",
        "      kit = GetContext().surface_manager.Fetch(kitFilename);",
        """      // Per-slot textures put real numbers on the animated shirt mesh.
      kitFilename = "media/objects/players/textures/demo_team_" +
                    int_to_str(GetID()) + "_player_" + int_to_str(i) + ".bmp";
      kit = GetContext().surface_manager.Fetch(kitFilename);""",
    )
    for old, new in (("Zoom = 0.5f", "Zoom = 0.7f"), ("Height = 0.3f", "Height = 0.5f")):
        replace_once(engine / "src/gamedefines.hpp", old, new)

    textures = engine / "data/media/objects/players/textures"
    kits = engine / "data/databases/default/images_teams/primeradivision"
    for team, kit_name in enumerate(("fcbarcelona", "realmadrid")):
        field = cv2.imread(str(kits / f"{kit_name}_kit_02.bmp"))
        goalie = cv2.imread(str(textures / "goalie_kit.bmp"))
        for slot, number in enumerate(SHIRT_NUMBERS[team]):
            image = numbered_kit(goalie if slot == 0 else field, number)
            path = textures / f"demo_team_{team}_player_{slot}.bmp"
            if not cv2.imwrite(str(path), image):
                raise OSError(f"Could not write {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    prepare(parser.parse_args().source)
