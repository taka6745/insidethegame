"""Fictional Elephant League lineups, not real people or clubs.

GRF_FIXTURE selects a capture's fixture (default riverton-forgeham); exports derive it from a recording's teams.
Names, codes, colours and players come from `league.json`. Slot order: GK, RM, CF, LB, CB, CB, RB, CM, CM, CM, LM.
"""

import json
import os
from pathlib import Path

LEAGUE = json.loads((Path(__file__).with_name("league.json")).read_text())

# kit: OpenCV (hue 0-180, saturation, value) for the recoloured kit; value None keeps shading.
# strip: RGB accent bar beside the team in the packaged score strip (and MA1 branding).
_KIT = {
    "chelsea": {"kit": (110, 225, None), "strip": (15, 80, 235)},
    "manutd": {"kit": (0, 225, None), "strip": (220, 20, 45)},
    "arsenal": {"kit": (178, 230, None), "strip": (219, 0, 7)},
    # Port Albion play in their off-white change kit in this fixture.
    "liverpool": {"kit": (20, 12, 235), "strip": (240, 236, 226)},
    "mancity": {"kit": (103, 140, 235), "strip": (108, 171, 221)},
    "tottenham": {"kit": (110, 8, 240), "strip": (245, 245, 245)},
}


def _team(key):
    club = LEAGUE["clubs"][key]
    team = {"id": club["id"], "name": club["name"], "known": club["known"], "code": club["code"], **_KIT[key]}
    if club["short"] != club["name"]:
        team["short"] = club["short"]
    return team


def _fixture(old, home, away, match_id, prefix, numbers):
    return LEAGUE["fixtures"][old], {
        "match_id": match_id,
        "event_prefix": prefix,
        "teams": [_team(home), _team(away)],
        "names": (tuple(LEAGUE["clubs"][home]["players"]), tuple(LEAGUE["clubs"][away]["players"])),
        "numbers": numbers,
    }


FIXTURES = dict((
    _fixture("chelsea-united", "chelsea", "manutd", "product-demo-match", "grf-rvr-fgu",
             ((1, 10, 9, 3, 6, 4, 24, 8, 25, 17, 7), (31, 19, 30, 23, 6, 4, 2, 8, 18, 37, 10))),
    _fixture("arsenal-liverpool", "arsenal", "liverpool", "redcastle-portalbion", "grf-rct-pal",
             ((1, 7, 14, 33, 2, 6, 12, 8, 41, 36, 10), (1, 11, 22, 6, 4, 5, 30, 8, 38, 7, 18))),
    _fixture("mancity-tottenham", "mancity", "tottenham", "skybridge-whitmore", "grf-skc-whw",
             ((25, 10, 9, 33, 3, 24, 27, 16, 4, 20, 11), (1, 20, 9, 13, 17, 37, 23, 6, 29, 15, 7))),
))

FIXTURE_NAME = os.environ.get("GRF_FIXTURE", "riverton-forgeham")
FIXTURE = FIXTURES[FIXTURE_NAME]
TEAMS = FIXTURE["teams"]
NAMES = FIXTURE["names"]
# Presentation numbers for these illustrative lineups, not a live squad feed.
SHIRT_NUMBERS = FIXTURE["numbers"]


def fixture_for(recording):
    """The fixture whose team ids the recording carries (GRF_FIXTURE when it names none)."""
    if "teams" not in recording:
        return FIXTURE
    ids = [team["id"] for team in recording["teams"]]
    return next(f for f in FIXTURES.values() if [t["id"] for t in f["teams"]] == ids)


def player_id(team, index, fixture=None):
    return f"{(fixture or FIXTURE)['teams'][team]['id']}-{index}"


def players(fixture=None):
    fixture = fixture or FIXTURE
    return [
        {"id": player_id(team, i, fixture), "name": name, "team_id": fixture["teams"][team]["id"]}
        for team, names in enumerate(fixture["names"])
        for i, name in enumerate(names)
    ]
