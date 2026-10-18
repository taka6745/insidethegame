"""Frozen wording/catalogue transfer cases; no runtime skill or agent dependency.

Sixteen stats inherit independent event-revision ledgers from the original gold
corpus. Four controls request unavailable data. Fictional names/IDs test supplied
catalogue grounding; this is not an unseen-domain or new-match benchmark.
Apply remap_fixture() before event adaptation and model-context construction.
"""
from .cases import cases


# Exact JSON string values only: event IDs, clocks, revisions and weights stay fixed.
ENTITY_REMAP = {
    "mbappe": "noah-laurent", "Kylian Mbappé": "Noah Laurent",
    "palmer": "mateo-silva", "Cole Palmer": "Mateo Silva",
    "colwill": "owen-reed", "Levi Colwill": "Owen Reed",
    "vinicius": "luca-costa", "Vinícius": "Luca Costa",
    "camavinga": "elias-nouri", "Camavinga": "Elias Nouri",
    "courtois": "hugo-voss", "Courtois": "Hugo Voss",
    "chelsea": "harbour", "Chelsea": "Harbour FC",
    "madrid": "ridge", "Madrid": "Ridge United",
}


def remap_fixture(value):
    """Return a copied JSON tree with consistent fictional entities, without I/O."""
    if isinstance(value, dict):
        return {key: remap_fixture(item) for key, item in value.items()}
    if isinstance(value, list):
        return [remap_fixture(item) for item in value]
    if isinstance(value, str):
        return ENTITY_REMAP.get(value, value)
    return value


# Original gold number, quality, new request, clarification reply (only if needed).
STAT_REQUESTS = [
    (8, "clear", "Keep tally of Noah Laurent's passes using his head, successful or otherwise.",
     "Count his headed passes, regardless of outcome."),
    (13, "average", "Noah Laurent's headed attempts that the keeper stops — can I see that count?",
     "Shots saved by the goalkeeper, not saves made by Noah."),
    (72, "clear", "Count Noah Laurent's shots saved by the opposing goalkeeper during the second half.",
     "Noah is the shooter; only his second-half saved shots."),
    (82, "average", "How many saves has Hugo Voss made? Keep that number on screen.",
     "Hugo is the goalkeeper making the saves."),
    (90, "clear", "Count Harbour FC clearances in the first half, with first-half injury time included.",
     "Use the first-half period, including added time."),
    (88, "average", "Harbour FC tackles that succeeded, as a running total please.",
     "Successful tackle events only."),
    (77, "average", "Keep Ridge United's yellows on the screen as a count.",
     "Yellow-card events for Ridge United."),
    (84, "average", "How many fouls has Mateo Silva committed in this game?",
     "Fouls committed by Mateo, not fouls against him."),
    (51, "clear", "Add up the recorded metres of Harbour FC's unsuccessful passes. I want distance, not a pass count.",
     "Sum distance for failed passes only."),
    (54, "average", "Total metres of completed passes after half-time, both sides together.",
     "Successful passes in the second-half period."),
    (97, "clear", "One counter for Harbour FC's goals and corners combined in the second half.",
     "Count either a goal or a corner, second half only."),
    (69, "clear", "Count shot attempts saved by the keepers, with shooters from either side included.",
     "Saved shot events for both teams, not goalkeeper save events."),
    (5, "ambiguous", "Track our headed contacts across all event types.",
     "Harbour FC."),
    (99, "ambiguous", "Track his completed-pass distance in metres since 80:00, including 80:00.",
     "Mateo Silva."),
    (23, "ambiguous", "Count both teams' corners strictly after that minute.",
     "After 60:00; exclude anything exactly at 60:00."),
    (10, "ambiguous", "How many headed goals has that player scored?",
     "Mateo Silva."),
]

CONTROLS = [
    ("Show Noah Laurent's cumulative xG from the shot-quality values.",
     "Expected-goals values, not a count of shots or goals."),
    ("Track Harbour FC possession as a percentage of playing time.",
     "Possession time percentage, not pass share."),
    ("Count Mateo Silva's touches inside the penalty box using event locations.",
     "Only touches inside the box, determined by pitch coordinates."),
    ("Show the distance Owen Reed has run in metres so far.",
     "The player's running distance, not pass distance."),
]


def data_transfer_cases():
    original = cases()
    result = []
    for index, (number, quality, prompt, reply) in enumerate(STAT_REQUESTS, 1):
        gold = original[number - 1]
        result.append({**gold, "id": f"data-transfer-{index:02}",
                       "gold_case_id": gold["id"], "intent_id": f"data-intent-{number:03}",
                       "expected_rule": remap_fixture(gold["expected_rule"]),
                       "prompt": prompt, "quality": quality,
                       "must_clarify": quality == "ambiguous", "replies": [reply]})
    result.extend({"id": f"data-control-{index:02}", "intent_id": f"data-control-{index:02}",
                   "prompt": prompt, "quality": "control", "expected_status": ["unsupported"],
                   "must_clarify": False, "replies": [reply]}
                  for index, (prompt, reply) in enumerate(CONTROLS, 1))
    return result
