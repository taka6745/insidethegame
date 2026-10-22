"""Hand-authored gold cases. Expected hits are explicit event/revision IDs.

Rules are written in the canonical event vocabulary they were authored in and translated to SPADL
(spadl_corpus.translate); an intent SPADL cannot express is an expected refusal or catalogue reuse.

Never derive gold answers from the agent or production filter evaluator.
Use `python -m benchmarks.correctness` to check every delivery and gold rule.
"""
from .spadl_corpus import translate

MATCH = "filter-lab-match"


def case(prompt, hits, quality="clear", operation="count", **terms):
    predicates = []
    for field, value in terms.items():
        field, _, op = field.partition("__")
        predicates.append({"field": field, "op": op or ("in" if isinstance(value, list) else "eq"), "value": value})
    weights = {}
    for item in hits.split():
        event, _, amount = item.partition(":")
        weights[event if "@" in event else event + "@1"] = float(amount) if amount else 1
    rule, reason = translate({"match_id": MATCH, "operation": operation, "predicates": predicates,
                              "sum_field": "distance_metres" if operation == "sum" else None})
    if rule is None:
        return {"prompt": prompt, "quality": quality, "expected_status": ["unsupported", "reuse"], "spadl_gap": reason}
    return {"prompt": prompt, "quality": quality, "expected_status": ["ready"], "expected_rule": rule,
            "expected_weights": weights}


# All identifiers below refer to fixtures/filter-lab.json, including superseded
# revisions. A missing revision contributes zero; deletions remove old values.
# SPADL (2026-10-21): "passes" are the pass family, so taken corners (corner_crossed) count as passes;
# the five pass-count intents gained their corner events. Only latest revisions carry an action.
CASES = [
    case("Count all recorded headed touches by Mbappé", "e1 e2 e7 e13 e18 e21@2 e26", player_id="mbappe", body_part="head"),
    case("mbappe headers second half pls", "e13 e18 e21@2 e26", "messy", player_id="mbappe", body_part="head", period=2),
    case("Mbappé headed touches in the first half, including stoppage time", "e1 e2 e7", player_id="mbappe", body_part="head", period=1),
    case("headers from everyone", "e1 e2 e7 e8 e13 e14 e18 e21@2 e22 e26", "average", body_part="head"),
    case("Chelsea recorded headed touches", "e8 e22", team_id="chelsea", body_part="head"),
    case("madrid headed touches", "e1 e2 e7 e13 e14 e18 e21@2 e26", "average", team_id="madrid", body_part="head"),
    case("Mbappé headed shot attempts including headed goals", "e2 e7 e13 e21@2", player_id="mbappe", body_part="head", event_type=["shot", "goal"]),
    case("mbappe head passes count", "e1 e18", "messy", player_id="mbappe", body_part="head", event_type="pass"),
    case("Mbappé headed goals", "e7", player_id="mbappe", body_part="head", event_type="goal"),
    case("Palmer headed goals", "e22", player_id="palmer", body_part="head", event_type="goal"),
    case("Count Colwill headed clearances", "e8", player_id="colwill", body_part="head", event_type="clearance"),
    case("vinicius head shots including goals", "e14", "messy", player_id="vinicius", body_part="head", event_type=["shot", "goal"]),
    case("saved headed Mbappé shots", "e2 e21@2", "average", player_id="mbappe", body_part="head", event_type="shot", outcome="saved"),
    case("Mbappé off-target headed shots", "e13", player_id="mbappe", body_part="head", event_type="shot", outcome="off_target"),
    case("headed touches since minute 20 inclusive", "e7 e8 e13 e14 e18 e21@2 e22 e26", body_part="head", match_time_seconds__gte=1200),
    case("headers before minute twenty", "e1 e2", "average", body_part="head", match_time_seconds__lt=1200),
    case("Count headed touches after 75:00, excluding 75:00 itself", "e22 e26", body_part="head", match_time_seconds__gt=4500),
    case("headers since 75:00 including that second", "e21@2 e22 e26", "average", body_part="head", match_time_seconds__gte=4500),
    case("First-half headed touches from either team", "e1 e2 e7 e8", body_part="head", period=1),
    case("second half all headers", "e13 e14 e18 e21@2 e22 e26", "messy", body_part="head", period=2),
    case("Chelsea corners awarded after minute 60", "e11 e15 e16 e17 e28 e29 e30", event_type="corner", team_id="chelsea", match_time_seconds__gt=3600),
    case("chelsea corners from 60 inclusive", "e10 e11 e15 e16 e17 e28 e29 e30", "average", event_type="corner", team_id="chelsea", match_time_seconds__gte=3600),
    case("corners after 60 all teams", "e11 e12 e15 e16 e17 e28 e28@2 e29 e30", "messy", event_type="corner", match_time_seconds__gt=3600),
    case("Count all corners awarded", "e3 e10 e11 e12 e15 e16 e17 e28 e28@2 e29 e30", event_type="corner"),
    case("Chelsea corners", "e3 e10 e11 e15 e16 e17 e28 e29 e30", "average", event_type="corner", team_id="chelsea"),
    case("Madrid corners", "e12 e28@2", event_type="corner", team_id="madrid"),
    case("first half corners", "e3", "average", event_type="corner", period=1),
    case("corners in second half", "e10 e11 e12 e15 e16 e17 e28 e28@2 e29 e30", "average", event_type="corner", period=2),
    case("Chelsea corners after 70 minutes", "e17 e28 e29 e30", event_type="corner", team_id="chelsea", match_time_seconds__gt=4200),
    case("Chelsea corners after 60 through 70 inclusive", "e11 e15 e16", event_type="corner", team_id="chelsea", match_time_seconds__gt=3600, match_time_seconds__lte=4200),
    case("corners before 60", "e3", "messy", event_type="corner", match_time_seconds__lt=3600),
    case("corners through 60:00 including that second", "e3 e10", event_type="corner", match_time_seconds__lte=3600),
    case("corners from 60:00 inclusive until 60:01 exclusive", "e10", event_type="corner", match_time_seconds__gte=3600, match_time_seconds__lt=3601),
    case("corners after ninety mins", "e30", "average", event_type="corner", match_time_seconds__gt=5400),
    case("Chelsea second half corners after 90:00", "e30", event_type="corner", team_id="chelsea", period=2, match_time_seconds__gt=5400),
    case("madrid corners after 70", "e28@2", "messy", event_type="corner", team_id="madrid", match_time_seconds__gt=4200),
    case("Chelsea corners before 30 minutes", "e3", event_type="corner", team_id="chelsea", match_time_seconds__lt=1800),
    case("all corners since 67 minutes inclusive", "e15 e16 e17 e28 e28@2 e29 e30", event_type="corner", match_time_seconds__gte=4020),
    case("corners from 60 up to but not including 61 minutes", "e10 e11", event_type="corner", match_time_seconds__gte=3600, match_time_seconds__lt=3660),
    case("corners after 88:00 but before 90:00", "e29", event_type="corner", match_time_seconds__gt=5280, match_time_seconds__lt=5400),
    case("Count all pass events", "e1 e4 e5 e18 e23 e3 e10 e11 e12 e15 e16 e17 e28@2 e30", event_type="pass"),
    case("Chelsea completed passes", "e4 e23 e3 e10 e11 e15 e16 e17 e30", event_type="pass", team_id="chelsea", outcome="success"),
    case("chelsea failed passes count", "e5", "messy", event_type="pass", team_id="chelsea", outcome="failure"),
    case("Mbappé passes", "e1 e18", event_type="pass", player_id="mbappe"),
    case("Palmer passes", "e4 e5 e23", event_type="pass", player_id="palmer"),
    case("all completed passes", "e1 e4 e18 e23 e3 e10 e11 e12 e15 e16 e17 e28@2 e30", "average", event_type="pass", outcome="success"),
    case("all failed passes", "e5", event_type="pass", outcome="failure"),
    case("Total recorded pass distance, both teams, in metres", "e1:8 e4:12 e5:20 e18:5 e23:15", operation="sum", event_type="pass"),
    case("sum chelsea pass metres all outcomes", "e4:12 e5:20 e23:15", "messy", operation="sum", event_type="pass", team_id="chelsea"),
    case("Chelsea successful pass distance in metres", "e4:12 e23:15", operation="sum", event_type="pass", team_id="chelsea", outcome="success"),
    case("Chelsea failed pass distance in metres", "e5:20", operation="sum", event_type="pass", team_id="chelsea", outcome="failure"),
    case("Mbappé headed pass distance in metres", "e1:8 e18:5", operation="sum", event_type="pass", player_id="mbappe", body_part="head"),
    case("palmer total pass distance metres", "e4:12 e5:20 e23:15", "average", operation="sum", event_type="pass", player_id="palmer"),
    case("second half completed pass distance in metres", "e18:5 e23:15", operation="sum", event_type="pass", period=2, outcome="success"),
    case("First-half pass distance in metres", "e1:8 e4:12 e5:20", operation="sum", event_type="pass", period=1),
    case("passes from either team after 70:00", "e18 e23 e17 e28@2 e30", event_type="pass", match_time_seconds__gt=4200),
    case("passes before 30 minutes", "e1 e4 e5 e3", "average", event_type="pass", match_time_seconds__lt=1800),
    case("right foot passes", "e4 e5 e23", "messy", event_type="pass", body_part="right_foot"),
    case("completed right-foot passes by Palmer", "e4 e23", event_type="pass", body_part="right_foot", player_id="palmer", outcome="success"),
    case("Palmer second-half pass metres", "e23:15", "average", operation="sum", event_type="pass", player_id="palmer", period=2),
    case("Goals by either team", "e7 e22", event_type="goal"),
    case("chelsea goals count", "e22", "messy", event_type="goal", team_id="chelsea"),
    case("Madrid goals", "e7", event_type="goal", team_id="madrid"),
    case("second half goals", "e22", "average", event_type="goal", period=2),
    case("first half goals", "e7", event_type="goal", period=1),
    case("Count all headed goals", "e7 e22", event_type="goal", body_part="head"),
    case("All shot attempts including goals", "e2 e7 e9 e13 e14 e21 e21@2 e22", event_type=["shot", "goal"]),
    case("Mbappé shot attempts including goals", "e2 e7 e9 e13 e21 e21@2", event_type=["shot", "goal"], player_id="mbappe"),
    case("saved shots both teams", "e2 e9 e14 e21 e21@2", "average", event_type="shot", outcome="saved"),
    case("off target shots count", "e13", "messy", event_type="shot", outcome="off_target"),
    case("right foot shot attempts including goals by mbappe", "e9 e21", "messy", event_type=["shot", "goal"], body_part="right_foot", player_id="mbappe"),
    case("second half saved shots by Mbappé", "e9 e21 e21@2", event_type="shot", player_id="mbappe", period=2, outcome="saved"),
    case("Count all card events", "e6 e20", event_type="card"),
    case("red cards", "e20", "average", event_type="card", outcome="red"),
    case("yellow cards count", "e6", "messy", event_type="card", outcome="yellow"),
    case("Chelsea red cards", "e20", event_type="card", team_id="chelsea", outcome="red"),
    case("Madrid yellow cards", "e6", event_type="card", team_id="madrid", outcome="yellow"),
    case("camavinga cards", "e6", "messy", event_type="card", player_id="camavinga"),
    case("Colwill cards", "e20", event_type="card", player_id="colwill"),
    case("cards after 60 minutes", "e20", event_type="card", match_time_seconds__gt=3600),
    case("Count all saves", "e24", event_type="save"),
    case("courtois saves", "e24", "average", event_type="save", player_id="courtois"),
    case("Chelsea fouls", "e25", event_type="foul", team_id="chelsea"),
    case("palmer fouls", "e25", "messy", event_type="foul", player_id="palmer"),
    case("Count Chelsea interceptions", "e27", event_type="interception", team_id="chelsea"),
    case("Palmer interceptions", "e27", event_type="interception", player_id="palmer"),
    case("colwill tackles", "e19", "average", event_type="tackle", player_id="colwill"),
    case("Chelsea successful tackles", "e19", event_type="tackle", team_id="chelsea", outcome="success"),
    case("Chelsea clearances", "e8", event_type="clearance", team_id="chelsea"),
    case("first half Chelsea clearances including added time", "e8", event_type="clearance", team_id="chelsea", period=1),
    case("Chelsea tackles, clearances and interceptions combined", "e8 e19 e27", event_type=["tackle", "clearance", "interception"], team_id="chelsea"),
    case("Chelsea second-half tackles, clearances and interceptions combined", "e19 e27", event_type=["tackle", "clearance", "interception"], team_id="chelsea", period=2),
    case("only events of type touch by Mbappé", "e26", event_type="touch", player_id="mbappe"),
    case("Mbappé recorded headed touches after 80 minutes", "e26", player_id="mbappe", body_part="head", match_time_seconds__gt=4800),
    case("Palmer goal events and pass events combined", "e4 e5 e22 e23", event_type=["goal", "pass"], player_id="palmer"),
    case("Count goal and card events combined", "e6 e7 e20 e22", event_type=["goal", "card"]),
    case("Chelsea goals or corners in the second half", "e10 e11 e15 e16 e17 e22 e28 e29 e30", event_type=["goal", "corner"], team_id="chelsea", period=2),
    case("Madrid headed touches through 10:00 inclusive", "e1 e2", team_id="madrid", body_part="head", match_time_seconds__lte=600),
    case("Palmer completed pass metres since 80:00 inclusive", "e23:15", operation="sum", event_type="pass", player_id="palmer", outcome="success", match_time_seconds__gte=4800),
    case("Mbappé headed touches after 60:00 and before 75:00", "e13 e18", player_id="mbappe", body_part="head", match_time_seconds__gt=3600, match_time_seconds__lt=4500),
]

NEGATIVE_CASES = [
    ("Track his headers", ["clarification"]),
    ("Track our corners", ["clarification"]),
    ("How much pressure are they putting on?", ["clarification", "unsupported"]),
    ("Track Haaland headers in this match", ["clarification"]),
    ("Track Arsenal corners", ["clarification"]),
    ("Track Chelsea corners in the last five minutes, continuously sliding", ["unsupported"]),
    ("Count sequences of five uninterrupted Madrid passes", ["unsupported"]),
    ("Track Chelsea corners only while Chelsea are losing", ["unsupported"]),
    ("Track the ratio of Chelsea passes to Madrid passes", ["unsupported"]),
    ("Track xG for Mbappé", ["unsupported"]),
    ("Count Mbappé's aerial duels won", ["unsupported"]),
    ("Track how tired Palmer looks", ["unsupported"]),
]


def cases():
    assert len(CASES) == 100
    result = [{"id": f"stat-{i:03}", **row} for i, row in enumerate(CASES, 1)]
    result += [{"id": f"negative-{i:02}", "prompt": prompt, "quality": "ambiguous_or_unsupported",
                "expected_status": status} for i, (prompt, status) in enumerate(NEGATIVE_CASES, 1)]
    return result
