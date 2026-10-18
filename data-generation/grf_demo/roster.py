"""Illustrative named lineups, not a claim of current or official selection."""

TEAMS = [
    {"id": "chelsea", "name": "Chelsea"},
    {"id": "manutd", "name": "Manchester United"},
]
NAMES = (
    (
        "Robert Sánchez",
        "Cole Palmer",
        "Liam Delap",
        "Marc Cucurella",
        "Levi Colwill",
        "Tosin Adarabioyo",
        "Reece James",
        "Enzo Fernández",
        "Moisés Caicedo",
        "Andrey Santos",
        "Pedro Neto",
    ),
    (
        "Senne Lammens",
        "Bryan Mbeumo",
        "Benjamin Šeško",
        "Luke Shaw",
        "Lisandro Martínez",
        "Matthijs de Ligt",
        "Diogo Dalot",
        "Bruno Fernandes",
        "Casemiro",
        "Kobbie Mainoo",
        "Matheus Cunha",
    ),
)


def player_id(team, index):
    return f"{TEAMS[team]['id']}-{index}"


def players():
    return [
        {"id": player_id(team, i), "name": name, "team_id": TEAMS[team]["id"]}
        for team, names in enumerate(NAMES)
        for i, name in enumerate(names)
    ]
