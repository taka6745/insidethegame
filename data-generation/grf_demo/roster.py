"""Illustrative named lineups, not a claim of current or official selection.

GRF_FIXTURE selects the fixture for a capture (default chelsea-united); exports derive the
fixture from a recording's teams. Names and presentation shirt numbers follow each club's
2025/26 first-team squad as listed on its English Wikipedia 2025–26 season page (checked
2026-10-20); kit colours are the club's 2025/26 kit as worn in that fixture. Slot order matches
the scenario: GK, RM, CF, LB, CB, CB, RB, CM, CM, CM, LM. Abilities stay generic.
"""

import os

# kit: OpenCV (hue 0-180, saturation, value) for the recoloured kit; value None keeps shading.
# strip: RGB accent bar beside the team in the packaged score strip (and MA1 branding).
# short: MA1 shortName when it differs from name. known: MA1 knownNames, other names fans and commentators use.
FIXTURES = {
    "chelsea-united": {
        "match_id": "product-demo-match",  # Bound to the shipped recording's checksum.
        "event_prefix": "grf-che-utd",
        "teams": [
            {"id": "chelsea", "name": "Chelsea", "known": ["the Blues"],
             "code": "CHE", "kit": (110, 225, None), "strip": (15, 80, 235)},
            {"id": "manutd", "name": "Manchester United", "short": "Man Utd", "known": ["United", "the Red Devils"],
             "code": "MUN", "kit": (0, 225, None),
             "strip": (220, 20, 45)},
        ],
        "names": (
            ("Robert Sánchez", "Cole Palmer", "Liam Delap", "Marc Cucurella", "Levi Colwill",
             "Tosin Adarabioyo", "Reece James", "Enzo Fernández", "Moisés Caicedo", "Andrey Santos",
             "Pedro Neto"),
            ("Senne Lammens", "Bryan Mbeumo", "Benjamin Šeško", "Luke Shaw", "Lisandro Martínez",
             "Matthijs de Ligt", "Diogo Dalot", "Bruno Fernandes", "Casemiro", "Kobbie Mainoo",
             "Matheus Cunha"),
        ),
        "numbers": (
            (1, 10, 9, 3, 6, 4, 24, 8, 25, 17, 7),
            (31, 19, 30, 23, 6, 4, 2, 8, 18, 37, 10),
        ),
    },
    "arsenal-liverpool": {
        "match_id": "arsenal-liverpool",
        "event_prefix": "grf-ars-liv",
        "teams": [
            # Arsenal home red; Liverpool in their 2025/26 off-white away kit.
            {"id": "arsenal", "name": "Arsenal", "known": ["the Gunners"],
             "code": "ARS", "kit": (178, 230, None), "strip": (219, 0, 7)},
            {"id": "liverpool", "name": "Liverpool", "known": ["the Reds"], "code": "LIV", "kit": (20, 12, 235),
             "strip": (240, 236, 226)},
        ],
        "names": (
            ("David Raya", "Bukayo Saka", "Viktor Gyökeres", "Riccardo Calafiori", "William Saliba",
             "Gabriel Magalhães", "Jurriën Timber", "Martin Ødegaard", "Declan Rice", "Martín Zubimendi",
             "Eberechi Eze"),
            ("Alisson Becker", "Mohamed Salah", "Hugo Ekitike", "Milos Kerkez", "Virgil van Dijk",
             "Ibrahima Konaté", "Jeremie Frimpong", "Dominik Szoboszlai", "Ryan Gravenberch",
             "Florian Wirtz", "Cody Gakpo"),
        ),
        "numbers": (
            (1, 7, 14, 33, 2, 6, 12, 8, 41, 36, 10),
            (1, 11, 22, 6, 4, 5, 30, 8, 38, 7, 18),
        ),
    },
    "mancity-tottenham": {
        "match_id": "mancity-tottenham",
        "event_prefix": "grf-mci-tot",
        "teams": [
            # City home sky blue; Spurs home white.
            {"id": "mancity", "name": "Manchester City", "short": "Man City", "known": ["City", "the Cityzens"],
             "code": "MCI", "kit": (103, 140, 235),
             "strip": (108, 171, 221)},
            {"id": "tottenham", "name": "Tottenham Hotspur", "short": "Spurs", "known": ["Tottenham", "the Lilywhites"],
             "code": "TOT", "kit": (110, 8, 240),
             "strip": (245, 245, 245)},
        ],
        "names": (
            ("Gianluigi Donnarumma", "Rayan Cherki", "Erling Haaland", "Nico O'Reilly", "Rúben Dias",
             "Joško Gvardiol", "Matheus Nunes", "Rodri", "Tijjani Reijnders", "Bernardo Silva",
             "Jérémy Doku"),
            ("Guglielmo Vicario", "Mohammed Kudus", "Richarlison", "Destiny Udogie", "Cristian Romero",
             "Micky van de Ven", "Pedro Porro", "João Palhinha", "Pape Matar Sarr", "Lucas Bergvall",
             "Xavi Simons"),
        ),
        "numbers": (
            (25, 10, 9, 33, 3, 24, 27, 16, 4, 20, 11),
            (1, 20, 9, 13, 17, 37, 23, 6, 29, 15, 7),
        ),
    },
}

FIXTURE_NAME = os.environ.get("GRF_FIXTURE", "chelsea-united")
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
