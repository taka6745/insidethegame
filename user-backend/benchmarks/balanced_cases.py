"""Frozen prompt-quality cohort: each cases.py gold intent in three wordings of differing clarity; missing
information is supplied only if the agent asks.
"""
from benchmarks.cases import cases

# gold case number, clear wording, average wording, poor wording, must clarify poor
INTENTS = [
    (1, "Count every headed contact Mbappé makes this match, across all event types.",
     "Track Mbappé's headers this game.", "his headers pls", True),
    (2, "Count Mbappé's headed contacts in the second half, across all event types.",
     "Mbappé headers, second half only.", "mbape hed touches 2nd half pls", False),
    (7, "Count Mbappé's headed shot attempts, including goals, throughout the match.",
     "Mbappé headed shots including goals.", "his head shots incl goals", True),
    (9, "Count goals scored with the head by Mbappé throughout the match.",
     "How many headed goals for Mbappé?", "mbappe head goalls", False),
    (11, "Count Rivas's headed clearances throughout the match.",
     "Rivas headed clearances please.", "that player's head clearances", True),
    (13, "Count Mbappé's headed shots that were saved throughout the match.",
     "Mbappé headers that the keeper saved.", "mbape head shots savd", False),
    (21, "Count Riverton Rovers corners strictly after 60:00, excluding the exact boundary.",
     "Riverton Rovers corners after the 60th minute.", "our corners after 60", True),
    (22, "Count Riverton Rovers corners from 60:00 onward, including 60:00.",
     "Riverton Rovers corners since minute 60, including that minute's start.", "chelse cornr frm 60 inclusive", False),
    (30, "Count Riverton Rovers corners strictly after 60:00 and up to 70:00 inclusive.",
     "Riverton Rovers corners after 60 through 70, include 70 itself.", "Riverton Rovers corners between 60 and 70", True),
    (33, "Count all corners from 60:00 inclusive until 60:01 exclusive.",
     "Corners from 60:00, stop before 60:01.", "corners in that second", True),
    (35, "Count Riverton Rovers second-half corners strictly after 90:00.",
     "Riverton Rovers second-half corners after 90 minutes.", "chelse 2nd half corners aft 90", False),
    (41, "Count every pass event from both teams, regardless of outcome.",
     "All passes, either team, successful or not.", "all pass events both sides any outcom", False),
    (42, "Count Riverton Rovers' completed passes throughout the match.",
     "Riverton Rovers completed passes.", "our completed passes", True),
    (43, "Count Riverton Rovers' failed passes throughout the match.",
     "Riverton Rovers incomplete passes please.", "chelse faild pases count", False),
    (48, "Sum the recorded distance of all passes from both teams in metres.",
     "Total pass metres, both sides, all outcomes.", "track passing for both sides", True),
    (50, "Sum Riverton Rovers' recorded completed-pass distance in metres throughout the match.",
     "Riverton Rovers successful pass metres.", "chelse completed pas dist metres", False),
    (52, "Sum the recorded distance of Mbappé's headed passes in metres.",
     "Mbappé headed pass metres.", "his head pass distance metres", True),
    (59, "Count Ashworth's completed right-footed passes throughout the match.",
     "Ashworth successful passes with his right foot.", "ashworth right foot completed pases", False),
    (60, "Sum Ashworth's recorded second-half pass distance in metres, for all outcomes.",
     "Ashworth second-half pass metres, successful or not.", "ashworth pass distance this half", True),
    (61, "Count all goals scored by either team throughout the match.",
     "Goals for both teams combined.", "all goals both sides", False),
    (67, "Count all shot attempts from either team, including goals.",
     "Total shots including goals, everyone.", "both sides shots incl goals", False),
    (70, "Count shots from either team that went off target throughout the match.",
     "All off-target shots please.", "off targt shots both", False),
    (72, "Count Mbappé's second-half shots that were saved.",
     "Mbappé saved shots in the second half.", "his saved shots 2nd half", True),
    (74, "Count all red-card events throughout the match.",
     "Red cards, both teams.", "red crds all", False),
    (77, "Count Real Madrid's yellow-card events throughout the match.",
     "Madrid yellow cards.", "our yellows", True),
    (82, "Count all saves made by Courtois throughout the match.",
     "Courtois saves this game.", "his saves", True),
    (83, "Count all fouls committed by Riverton Rovers throughout the match.",
     "Riverton Rovers fouls committed.", "chelse fouls commited", False),
    (86, "Count all interception events by Ashworth throughout the match.",
     "Ashworth interceptions.", "that player's interceptions", True),
    (91, "Count Riverton Rovers tackles, clearances and interceptions combined throughout the match.",
     "Riverton Rovers tackles plus clearances plus interceptions.", "our tackles clearances interceptions combined", True),
    (100, "Count Mbappé's headed contacts strictly after 60:00 and strictly before 75:00.",
     "Mbappé headers after 60, before 75; exclude both boundaries.", "mbappe headers between 60 and 75", True),
]

CONTROLS = [
    "Track Riverton Rovers corners in a continuously sliding five-minute window.",
    "Track the ratio of Riverton Rovers passes to Real Madrid passes.",
    "Count sequences of five uninterrupted Real Madrid passes.",
    "Count Riverton Rovers corners only while Riverton Rovers are losing.",
    "Track Mbappé's expected-goals total, using xG values.",
    "Count Mbappé's aerial duels won, using contested headers.",
    "Track how tired Ashworth looks from watching the video.",
    "Calculate Ashworth's average running speed in kilometres per hour.",
    "Track the distance Ashworth has run, not the distance of his passes.",
    "Predict whether Mbappé will score another goal later in this match.",
]


def balanced_cases():
    original = cases()
    assert len(INTENTS) == 30 and len(CONTROLS) == 10
    result = []
    for index, (number, clear, average, poor, must_clarify) in enumerate(INTENTS, 1):
        for quality, prompt in (("clear", clear), ("average", average), ("poor", poor)):
            result.append({**original[number - 1], "id": f"balanced-{index:02}-{quality}",
                "intent_id": f"intent-{index:02}", "gold_case_id": original[number - 1]["id"],
                "prompt": prompt, "quality": quality,
                "must_clarify": must_clarify if quality == "poor" else False,
                "replies": [f"I mean: {clear}", f"Please use this exact meaning: {clear}"],
                "expected_status": original[number - 1]["expected_status"]})
    result.extend({"id": f"balanced-control-{index:02}", "intent_id": f"control-{index:02}",
        "prompt": prompt, "quality": "control", "must_clarify": False,
        "replies": [f"Yes, specifically this request: {prompt}", f"I still mean: {prompt}"],
        "expected_status": ["unsupported"]} for index, prompt in enumerate(CONTROLS, 1))
    assert len(result) == 100
    return result
