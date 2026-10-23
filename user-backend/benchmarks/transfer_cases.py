"""New wording for additional known gold intents, excluded from balanced selection.

This is a transfer check across known football/filter semantics, not a fully
held-out new-domain evaluation. Runtime prompts remain frozen while it runs.
"""
from benchmarks.cases import cases

# Gold case number, independently written request, optional short clarification.
REQUESTS = [
    (3, "Keep a count of every time Mbappé uses his head in the first half, including added time.",
     "All headed contacts, through the first-half whistle."),
    (8, "I'd like a running count of Mbappé's passes made with his head, whether they reach a teammate or not.",
     "Count headed passes, any outcome."),
    (12, "How many attempts has Vinícius made with his head? Keep any that go in in the total too.",
     "Headed shots, including goals."),
    (14, "Track Mbappé's headers that miss the target when he's shooting.",
     "Off-target headed shots only."),
    (19, "Add up all headed contacts from both sides before half-time, including first-half stoppage time.",
     "Count contacts across every event type, first half only."),
    (27, "Show me how many corners either side got in the first half, including added time.",
     "Both teams combined, first half only."),
    (36, "Keep counting Real Madrid corners after 70:00; don't include one exactly at 70:00.",
     "Strictly later than 70:00."),
    (39, "Count either team's corners starting exactly at 60:00, but stop before 61:00.",
     "Include 60:00 and exclude 61:00."),
    (49, "Add together the distance of Riverton Rovers' passes in metres, including their unsuccessful passes.",
     "Total pass distance, all outcomes."),
    (54, "How many metres do both teams' completed passes add up to in the second half? Keep that total updated.",
     "Only successful passes in the second half."),
    (80, "Track cards shown to either side strictly after the clock passes 60:00, red or yellow.",
     "All card events after 60:00, excluding the boundary."),
    (96, "Give me one combined count of goals and cards for both teams throughout this match.",
     "Count each goal or card event once."),
]


def transfer_cases():
    original = cases()
    return [{**original[number - 1], "id": f"transfer-{index:02}",
             "intent_id": f"transfer-intent-{number:03}",
             "gold_case_id": original[number - 1]["id"],
             "prompt": prompt, "quality": "transfer", "must_clarify": False,
             "replies": [reply], "expected_status": original[number - 1]["expected_status"]}
            for index, (number, prompt, reply) in enumerate(REQUESTS, 1)]
