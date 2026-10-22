"""The analyst's grounding validator and the storyline reducer, on small hand-made inputs (synthetic teams)."""
import asyncio
import re

from narrative_engine.analysis.policy import ShippedPolicy
from narrative_engine.analysis.storylines import choose_focus, reduce
from narrative_engine.analysis.validator import (claim_reasons, claim_reasons_many, ledger_facts, merge,
                                                 narrative_reasons, parse, prompt_limits, repair_request, validate)
from narrative_engine.context.render import MatchInfo, render_storylines, render_trend_table, render_trends
from narrative_engine.core.models import MatchClock
from narrative_engine.devtools.fake_decisions import FakeDecisions

INFO = MatchInfo.from_ma1({"matchId": "m", "contestant": [
    {"id": "riv", "name": "Riverside FC", "code": "RIV", "position": "home",
     "lineup": [{"playerId": "p9", "name": "Ada Mensah"}, {"playerId": "p4", "name": "Bo Kerr"}]},
    {"id": "har", "name": "Harbour Town", "code": "HAR", "position": "away", "lineup": []}]})
CLOCK = MatchClock(1, 29)
POLICY = ShippedPolicy().policy
BEATS = POLICY.storylines["beats_shown"]
RULES, STORY = POLICY.analysis, POLICY.storylines
MAX_ACTIVE = STORY["max_active"]
HORIZON = [1, 29, 59]


def row(indicator, team, window, value, level=None, previous=None, trend=None):
    return {"indicator": indicator, "contestantId": team, "window": window, "minutes": 15, "value": value,
            "previous": previous, "delta": None, "level": level, "trend": trend}


TRENDS = [row("field_tilt", "riv", "last15", 0.7811, "high", 0.6302, "rising"), row("field_tilt", "har", "last15", 0.2189),
          row("possession", "riv", "match", 0.5347), row("possession", "har", "match", 0.4653),
          row("box_entries", "har", "last5", 7.0, "high")]
GOAL = {"id": 11, "keyType": "Goal", "detail": None, "contestantId": "riv", "playerId": "p9", "periodId": 1,
        "timeMin": 27, "timeSec": 10}
LEDGER = [GOAL]


def observation(**over):
    base = {"label": "Riverside squeeze the pitch", "team": "RIV", "confidence": 0.7, "storyline": "open",
            "headline": "Riverside have tilted the pitch: 78% of final-third play in the last 15 minutes.",
            "explanation": "Up from 0.63 before that.",
            "evidence": [{"indicator": "field_tilt", "team": "RIV", "window": "last15", "value": 0.78}]}
    return {**base, **over}


def check(*observations, lines=(), resolve=()):
    return validate({"observations": list(observations), "resolve": list(resolve)}, TRENDS, LEDGER, list(lines),
                    INFO, CLOCK, rules=RULES)


def test_a_grounded_observation_in_the_models_own_words_is_accepted():
    accepted, resolves, rejected = check(observation())
    assert rejected == [] and resolves == []
    assert accepted[0]["team"] == "riv" and accepted[0]["facts"] == [TRENDS[0]]
    goals = observation(label="Ada Mensah's opener", evidence=[{"indicator": "goals", "team": "riv", "window": "match",
                                                                 "value": 1}],
                        headline="Ada Mensah's goal puts Riverside 1 up.", explanation=None, confidence=0.9)
    assert check(goals)[2] == []  # key-event facts are citable rows; a scorer in the ledger may be named


def test_ungrounded_observations_are_dropped_with_reasons():
    cases = {
        "value": observation(evidence=[{"indicator": "field_tilt", "team": "RIV", "window": "last15", "value": 0.9}]),
        "window": observation(evidence=[{"indicator": "field_tilt", "team": "RIV", "window": "match", "value": 0.78}]),
        "unknown indicator": observation(evidence=[{"indicator": "xg", "team": "RIV", "window": "last15",
                                                    "value": 0.78}]),
        "no evidence": observation(evidence=[]),
        "wrong team": observation(team="HAR"),
        "number": observation(headline="Riverside have 64% of the final-third play."),
        "other team named": observation(explanation="Harbour Town cannot get out."),
        "player not in ledger": observation(explanation="Bo Kerr is everywhere."),
        "xg": observation(explanation="Their xG is climbing."),
        "cap": observation(confidence=0.95),
        "short cap": observation(label="Harbour in the box", team="HAR", confidence=0.7, headline="Harbour Town keep "
                                 "arriving in the box.", explanation=None, evidence=[
                                     {"indicator": "box_entries", "team": "HAR", "window": "last5", "value": 7}]),
        "label": observation(label="x"),
        "storyline": observation(storyline="sl:m:9"),
    }
    for name, item in cases.items():
        accepted, _, rejected = check(item)
        assert accepted == [] and rejected and rejected[0]["reasons"], name
    assert check(cases["short cap"] | {"confidence": 0.6})[2] == []
    assert check(observation(explanation="It is the result of patient build-up."))[2] == []  # results: a claim question
    assert validate(parse("I think Riverside are on top."), TRENDS, LEDGER, [], INFO, CLOCK, rules=RULES)[2][0]["reasons"] == \
        ["reply is not a JSON object"]
    assert parse('```json\n{"observations": []}\n```') == {"observations": []}


def test_ledger_facts_are_goals_and_red_cards_per_team():
    facts = ledger_facts(LEDGER, INFO)
    assert [(f["indicator"], f["contestantId"], f["value"]) for f in facts] == [
        ("goals", "riv", 1), ("red_cards", "riv", 0), ("goals", "har", 0), ("red_cards", "har", 0)]


def analyse(lines, observations=(), resolve=(), clock=CLOCK, horizon=HORIZON, ledger=LEDGER, final=False, n=1,
            story=None):
    accepted, resolves, rejected = validate({"observations": list(observations), "resolve": list(resolve)}, TRENDS,
                                            ledger, lines, INFO, clock, rules=RULES)
    assert rejected == []
    return reduce(lines, accepted, resolves, ledger, match_id="m", analysis_id=f"a{n}", clock=clock, horizon=horizon,
                  final=final, rules=story or STORY, final_outcome="Full time: Riverside FC 1-0 Harbour Town.")


def test_storylines_open_develop_go_dormant_and_resolve():
    lines = analyse([], [observation()], horizon=[1, 24, 59])
    [line] = lines
    assert (line["id"], line["label"], line["team"], line["status"]) == ("sl:m:1", "Riverside squeeze the pitch", "riv",
                                                                         "active")
    assert line["salience"] == 0.8 and line["beats"][0]["evidence"] == [TRENDS[0]]
    again = observation(storyline=None, label="riverside  SQUEEZE the pitch")  # same label: develops, never duplicates
    lines = analyse(lines, [again], n=2)
    assert len(lines) == 1 and len(lines[0]["beats"]) == 2 and lines[0]["keyEventIds"] == [11]  # 27' goal linked
    assert lines[0]["salience"] == round(0.7 + 0.2 + 0.5, 4)
    lines = analyse(lines, n=3)
    assert lines[0]["status"] == "active" and lines[0]["quiet"] == 1
    lines = analyse(lines, n=4)
    assert lines[0]["status"] == "dormant"
    lines = analyse(lines, [observation(storyline="sl:m:1")], n=5)
    assert lines[0]["status"] == "active" and lines[0]["quiet"] == 0  # developing revives it
    for n in range(6, 10):
        lines = analyse(lines, n=n)
    assert lines[0]["status"] == "resolved" and lines[0]["outcome"].startswith("Closed")
    back = analyse(lines, [observation()], n=10)  # within `reopen_within` minutes the same label reopens it
    assert len(back) == 1 and back[0]["status"] == "active" and back[0]["outcome"] is None
    assert back[0]["resolutions"][0]["outcome"].startswith("Closed") and len(back[0]["beats"]) == 4
    later = analyse(lines, [observation()], n=10, story={**STORY, "reopen_within": -1})
    assert later[1]["id"] == "sl:m:2"  # outside the window it returns as a new one


def test_resolve_cap_and_full_time():
    lines = analyse([], [observation(label=f"Thread {'abcde'[i]}", confidence=0.5 + i / 10)
                         for i in range(MAX_ACTIVE + 1)])
    assert [s["status"] for s in lines].count("active") == MAX_ACTIVE
    assert next(s for s in lines if s["status"] == "dormant")["label"] == "Thread a"  # the least salient
    resolved = analyse(lines, resolve=[{"storyline": "sl:m:5", "outcome": "Riverside turned it into a goal."}], n=9)
    assert next(s for s in resolved if s["id"] == "sl:m:5")["outcome"] == "Riverside turned it into a goal."
    final = analyse(lines, final=True, n=10)
    assert all(s["status"] == "resolved" for s in final)
    assert {s["outcome"] for s in final} == {"Full time: Riverside FC 1-0 Harbour Town."}


def test_focus_is_chosen_by_rule_and_rotates():
    lines = analyse([], [observation(),
                         observation(label="Harbour keep coming", team="HAR", confidence=0.6, explanation=None,
                                     headline="Harbour Town keep arriving in the box.",
                                     evidence=[{"indicator": "box_entries", "team": "HAR", "window": "last5",
                                                "value": 7.0}])])
    top = choose_focus(lines, "scheduled", rules=STORY)
    assert top["id"] == "sl:m:1"
    assert choose_focus(lines, "scheduled", rules=STORY, recent=["sl:m:1"])["id"] == "sl:m:2"
    away_goal = {**GOAL, "contestantId": "har"}
    assert choose_focus(lines, "keyEvent", rules=STORY, key_row=away_goal)["id"] == "sl:m:2"
    assert choose_focus(lines, "storylineTurn", rules=STORY, turned="sl:m:2")["id"] == "sl:m:2"
    assert choose_focus([], "scheduled", rules=STORY) is None
    final = analyse(lines, final=True, n=2)
    assert choose_focus(final, "fullTime", rules=STORY, analysis_id="a2")["id"] == "sl:m:1"


def test_rendering_shows_ids_to_the_analyst_and_the_focus_to_the_author():
    lines = analyse([], [observation()])
    analyst = render_storylines(lines, INFO, LEDGER, beats=BEATS)
    assert analyst.startswith("- sl:m:1 [Riverside squeeze the pitch] (active; since 30')")
    author = render_storylines(lines, INFO, LEDGER, focus="sl:m:1", ids=False, beats=BEATS)
    assert author.startswith('- FOCUS "Riverside squeeze the pitch" (active; since 30\')') and "sl:m" not in author
    table = render_trends(TRENDS, INFO)
    assert "[last15: last 15 minutes] Riverside FC (RIV): field_tilt 0.78 (high, rising from 0.63)" in table
    assert "possession" not in render_trends(TRENDS, INFO, flagged_only=True).split("[match")[0]
    kept = render_trends(TRENDS, INFO, flagged_only=True, always=POLICY.storylines["author_match_indicators"])
    assert "[match: whole match] Riverside FC (RIV): possession 0.53" in kept
    analyst = render_trend_table(TRENDS + ledger_facts(LEDGER, INFO), INFO)
    assert analyst.splitlines()[:3] == ["Teams: RIV = Riverside FC (home), HAR = Harbour Town (away).",
                                        'window "last5" (last 5 minutes):', "  box_entries: HAR 7.00 (high)"]
    assert "  field_tilt: RIV 0.78 (high, rising from 0.63) | HAR 0.22" in analyst
    assert "  goals: RIV 1.00 | HAR 0.00" in analyst
    # Served labels and plain-words meanings: the author reads the label, both get what each measures.
    named = [{**r, "label": "field tilt", "meaning": "their share of the play in the final thirds"}
             if r["indicator"] == "field_tilt" else r for r in TRENDS]
    author = render_trends(named, INFO)
    assert "Riverside FC (RIV): field tilt 0.78 (high, rising from 0.63)" in author and "field_tilt" not in author
    assert author.endswith("What each measures:\n- field tilt: their share of the play in the final thirds")
    assert render_trend_table(named, INFO).endswith(
        "What each indicator measures:\n- field tilt: their share of the play in the final thirds")
    # prev10 is last5's baseline, never a shown window: its flagged rows add no legend line.
    baseline = {**row("fouls", "riv", "prev10", 2.0, "notable"), "label": "fouls", "meaning": "fouls committed"}
    assert "fouls" not in render_trends(named + [baseline], INFO, flagged_only=True)
    assert "fouls" not in render_trend_table(named + [baseline], INFO)
    # A resolved storyline takes no more moves: the analyst sees no id for it.
    done = analyse(lines, resolve=[{"storyline": "sl:m:1", "outcome": "Riverside turned it into a goal."}], n=2)
    assert render_storylines(done, INFO, LEDGER, beats=BEATS).startswith('- "Riverside squeeze the pitch" (resolved: ')


def test_writers_see_trend_labels_never_ids_and_the_analyst_cites_by_label():
    """Every served trend carries a plain label: neither the author's trends nor the analyst's table shows an id it
    could copy into fan-facing text; the analyst's evidence names the label and the validator maps it back."""
    plain = {i: f"plain words {n}" for n, i in enumerate(dict.fromkeys(r["indicator"] for r in TRENDS))}
    labelled = [{**r, "label": plain[r["indicator"]], "meaning": "what it measures"} for r in TRENDS]
    ids = {r["indicator"] for r in TRENDS}
    author = render_trends(labelled, INFO)
    table = render_trend_table(labelled + ledger_facts(LEDGER, INFO), INFO)
    for text in (author, table):
        assert not any(re.search(rf"\b{i}\b", text) for i in ids | {"red_cards"})
    cite = {"indicator": plain["field_tilt"], "team": "RIV", "window": "last15", "value": 0.78}
    accepted, _, rejected = validate({"observations": [observation(evidence=[cite], storyline=None)], "resolve": []},
                                     labelled, LEDGER, [], INFO, CLOCK, rules=RULES)
    assert accepted and not rejected and accepted[0]["facts"][0]["indicator"] == "field_tilt"


def test_the_analysts_comparison_and_early_result_claims_go_back_for_repair():
    from narrative_engine.analysis.validator import analyst_claim_rejections
    claims = POLICY.claims
    lines = analyse([], [observation()])
    deeper = observation(label="Harbour sit deeper", storyline=None,
                         headline="Riverside have tilted the pitch while Harbour sit deeper.")
    resolve = {"storyline": "sl:m:1", "outcome": "Riverside never turned it into a winner."}
    reply = {"observations": [observation(storyline=None, label="Riverside tilt it"), deeper], "resolve": [resolve]}
    accepted, resolves, rejected = validate(reply, TRENDS, LEDGER, lines, INFO, CLOCK, rules=RULES)
    assert len(accepted) == 2 and len(resolves) == 1 and rejected == []
    model = FakeDecisions({"e1s1_comparison": 0.9, "e2s1_result": 0.9}, rule=lambda key, q, state:
                          0.9 if key.endswith("_support") and key.startswith("e0") else None)
    variables = {"storylines": "lines", "key_event_ledger": "ledger", "match_trends": "trends",
                 "analysis_reason": "Scheduled analysis at 30'."}
    kept, kept_resolves, rejected = asyncio.run(analyst_claim_rejections(reply, accepted, resolves, [], variables,
                                                                         model, claims))
    assert [o["label"] for o in kept] == ["Riverside tilt it"] and kept_resolves == []
    assert [r["item"] for r in rejected] == [deeper, resolve]  # the reply's own items, for the repair turn
    assert rejected[0]["reasons"][0].startswith(claims["comparison"]["repair"])
    assert rejected[1]["reasons"][0].startswith(claims["result"]["repair"])
    [(state, asked)] = model.calls
    assert "Scheduled analysis at 30'." in state  # the analyst's own inputs are the evidence
    assert not any("causal" in k for k in asked) and any("intent" in k for k in asked)  # the claims marked analyst
    cache = {}
    asyncio.run(analyst_claim_rejections(reply, accepted, resolves, [], variables, model, claims, cache))
    asyncio.run(analyst_claim_rejections(reply, accepted, resolves, [], variables, model, claims, cache))
    assert len(model.calls) == 2  # after a repair turn, items already asked are not asked again


def test_an_analyst_label_stating_intent_goes_back_for_repair():
    """The label becomes the storyline's name, so it faces the intent claim like any sentence the analyst writes."""
    from narrative_engine.analysis.validator import analyst_claim_rejections
    claims = POLICY.claims
    lines = analyse([], [observation()])
    fouls = observation(storyline=None, label="Riverside foul to disrupt Harbour's transitions",
                        headline="Riverside's fouls have risen.")
    reply = {"observations": [fouls], "resolve": []}
    accepted, resolves, rejected = validate(reply, TRENDS, LEDGER, lines, INFO, CLOCK, rules=RULES)
    model = FakeDecisions({"e0s1_intent": 0.9})  # the label's sentence claims intent; no support
    variables = {"storylines": "lines", "key_event_ledger": "ledger", "match_trends": "trends",
                 "analysis_reason": "Scheduled analysis at 30'."}
    kept, _, rejected = asyncio.run(analyst_claim_rejections(reply, accepted, resolves, [], variables, model, claims))
    assert kept == [] and [r["item"] for r in rejected] == [fouls]
    assert rejected[0]["reasons"][0].startswith(claims["intent"]["repair"])
    assert "Riverside foul to disrupt" in rejected[0]["reasons"][0]


def test_confidence_levels_and_their_caps():
    short = observation(label="Harbour in the box", team="HAR", headline="Harbour Town keep arriving in the box.",
                        explanation=None, evidence=[{"indicator": "box_entries", "team": "HAR", "window": "last5",
                                                     "value": 7}])
    assert check(short | {"confidence": "medium"})[0][0]["confidence"] == 0.6
    [rejected] = check(short | {"confidence": "high"})[2]
    assert "use 'low' or 'medium', or also cite a longer window" in rejected["reasons"][0]
    assert check(observation(confidence="High"))[0][0]["confidence"] == 0.8  # a longer window allows high
    assert check(observation(confidence="certain"))[2][0]["reasons"] == ["confidence must be one of 'low', 'medium', 'high'"]


def test_one_repair_turn_keeps_the_accepted_items_and_rechecks_the_rest():
    lines = analyse([], [observation()])
    good = observation(storyline="sl:m:1")
    bad = observation(label="Riverside press", storyline="sl:m:1", headline="Riverside win it back high.")
    reply = {"observations": [good, bad], "resolve": [{"storyline": "sl:m:9", "outcome": "Done."}]}
    accepted, _, rejected = validate(reply, TRENDS, LEDGER, lines, INFO, CLOCK, rules=RULES)
    assert len(accepted) == 1 and len(rejected) == 2 and "already moved by another observation" in \
        rejected[0]["reasons"][0]
    request = repair_request(rejected)
    assert 'observation "Riverside press": storyline sl:m:1 already moved' in request and "resolve of sl:m:9" in request
    still_double = merge(reply, rejected, {"observations": [bad]}, RULES)
    assert len(validate(still_double, TRENDS, LEDGER, lines, INFO, CLOCK, rules=RULES)[2]) == 1  # limits hold across both turns
    fixed = merge(reply, rejected, {"observations": [bad | {"storyline": None}, observation(label="Extra one")]}, RULES)
    accepted, _, rejected = validate(fixed, TRENDS, LEDGER, lines, INFO, CLOCK, rules=RULES)
    assert [a["label"] for a in accepted] == ["Riverside squeeze the pitch", "Riverside press"]  # one per rejection
    assert rejected == []
    assert merge(None, [], {"observations": []}, RULES) == {"observations": []}  # an unparseable first reply is replaced


def author_vars(**over):
    base = {"game_state_statistics": "Score: Riverside FC (home) 1 - 0 Harbour Town (away)\n| Possession | 64.3% | "
                                     "35.7% |",
            "match_trends": "[last15: last 15 minutes] Riverside FC (RIV): field_tilt 0.78 (high)",
            "storylines": '- FOCUS "Riverside squeeze the pitch" (active; since 15\')\n    25\' Riverside tilt it',
            "key_event_ledger": "- 27' 27:10: Goal for Riverside FC, Ada Mensah", "match_events": "No recorded events.",
            "trigger_reason": "Key event at 27' (27:10): Goal for Riverside FC, Ada Mensah",
            "combined_match_context": "[1'-26'] Harbour sat deep at Fairfield Park.", "user_type": "Supports Riverside",
            "narrative_excerpts": "None yet."}
    return {**base, **over}


def test_author_excerpts_use_only_served_numbers_and_names():
    ok = "Ada Mensah's goal at 27' puts Riverside ahead, with 64% of the ball and a 78% tilt at Fairfield Park."
    assert narrative_reasons(ok, author_vars(), INFO, CLOCK, rules=RULES) == []
    [numbers] = narrative_reasons("Riverside have 54.3% of the ball and twelve shots.", author_vars(), INFO,
                                  MatchClock(1, 9), rules=RULES)  # minutes up to the clock are allowed
    assert numbers.startswith("uses numbers not shown in the statistics, trends or storylines: 12, 54.3")
    [name] = narrative_reasons("Riverside lead through Jones, the Blues' captain.", author_vars(), INFO, CLOCK, rules=RULES)
    assert name.startswith("names Jones, Blues, which are not in the roster")
    # MA1 short and known names are team names: accepted, and the analyst must cover the team they name.
    known = MatchInfo.from_ma1({"matchId": "m", "contestant": [
        {"id": "riv", "name": "Riverside FC", "shortName": "Riverside", "knownNames": ["the Blues"], "code": "RIV",
         "position": "home", "lineup": []},
        {"id": "har", "name": "Harbour Town", "code": "HAR", "position": "away", "lineup": []}]})
    assert known.home.other_names == ("Riverside", "the Blues") and known.away.other_names == ()
    assert narrative_reasons("The Blues lead.", author_vars(), known, CLOCK, rules=RULES) == []
    [team] = validate({"observations": [observation(headline="Harbour Town watch the Blues tilt the pitch.",
                                                    explanation=None)]}, TRENDS, LEDGER, [], known, CLOCK,
                      rules=RULES)[2][0]["reasons"]
    assert team.startswith("headline names Harbour Town")
    assert narrative_reasons("Riverside's box entries are 1.40 per 90.", author_vars(), INFO, CLOCK, rules=RULES) == [
        "uses numbers not shown in the statistics, trends or storylines: 1.40 (quote numbers as shown; do not "
        "calculate new ones)", "the excerpt gives a rate per 90 minutes; the trend rates are per 5 minutes"]


def test_unsupported_causal_and_intent_claims_are_decision_questions_with_policy_thresholds():
    text = "Riverside's pressing pays off as Ada Mensah scores. Harbour sat deep on purpose."
    claims = POLICY.claims

    def reasons(answers, rules=claims):
        model = FakeDecisions(answers)
        return asyncio.run(claim_reasons(text, author_vars(), model, rules)), model.calls
    found, [(state, asked)] = reasons({"e0s1_causal": 0.9, "e0s1_causal_support": 0.2, "e0s2_intent": 0.8})
    assert found == [f"{claims['causal']['repair']}: \"Riverside's pressing pays off as Ada Mensah scores.\"",
                     f"{claims['intent']['repair']}: \"Harbour sat deep on purpose.\""]
    assert sorted(asked) == [f"e0s{i}_{c}{s}" for i in (1, 2)
                             for c in ("causal", "comparison", "intent", "result", "score") for s in ("", "_support")]
    assert asked["e0s2_intent"].instructions == (
        "The sentence: \"Harbour sat deep on purpose.\" (it follows: \"Riverside's pressing pays off as Ada Mensah "
        f"scores.\")\n{claims['intent']['claim']}")  # the sentence before gives "they"/"it" their team
    assert asked["e0s1_intent"].instructions.startswith("The sentence: \"Riverside's pressing pays off as Ada Mensah scores.\"\n")
    assert "Riverside tilt it" in state and "Goal for Riverside FC, Ada Mensah" in state  # the evidence: beats, ledger
    assert reasons({"e0s1_causal": 0.9, "e0s1_causal_support": 0.7})[0] == []  # a beat states the link
    strict = {**claims, "causal": {**claims["causal"], "min_support_probability": 0.8}}
    assert len(reasons({"e0s1_causal": 0.9, "e0s1_causal_support": 0.7}, strict)[0]) == 1
    off = {name: {**c, "enabled": False} for name, c in claims.items()}
    assert reasons({"e0s1_causal": 1.0}, off) == ([], [])
    batch = FakeDecisions({"e1s1_causal": 0.9})  # two excerpts with one evidence state: one call
    found = asyncio.run(claim_reasons_many([(text, author_vars()), ("Riverside win a corner.", author_vars())],
                                           batch, claims))
    assert len(batch.calls) == 1 and found == [[], [f"{claims['causal']['repair']}: \"Riverside win a corner.\""]]


def test_a_result_before_the_evidence_shows_the_end_is_a_claim_question_not_a_phrase_list():
    claims = POLICY.claims
    text = "Riverside have won the match."
    model = FakeDecisions({"e0s1_result": 0.9, "e0s1_result_support": 0.1})
    assert asyncio.run(claim_reasons(text, author_vars(), model, claims)) == [f"{claims['result']['repair']}: \"{text}\""]
    [(_, asked)] = model.calls  # one batched call with the cause and intent questions
    assert {"e0s1_causal", "e0s1_intent", "e0s1_result", "e0s1_result_support"} <= set(asked)
    ended = FakeDecisions({"e0s1_result": 0.9, "e0s1_result_support": 0.9})  # the evidence shows full time
    assert asyncio.run(claim_reasons(text, author_vars(), ended, claims)) == []
    assert narrative_reasons("Full time: the final whistle has gone.", author_vars(), INFO, CLOCK, rules=RULES) == []


def test_the_analyst_prompts_limits_are_filled_from_the_policy():
    from narrative_engine.agents.prompt_source import render_template, shipped
    limits = prompt_limits(RULES)
    assert limits == {"max_observations": 6, "max_evidence": 8, "confidence_levels": '"low", "medium" or "high"',
                      "short_windows": '"last5"', "short_window_levels": '"low" or "medium"'}
    prompt = shipped("match-analyst")
    text = render_template(prompt, {k: "" for k in ("analysis_reason", "game_state_statistics", "key_event_ledger",
                                                    "combined_match_context", "match_trends", "storylines")} | limits)
    assert prompt.label == "match-analyst.v4" and "Up to 6 observations" in text and "1 to 8 evidence rows" in text
    tight = prompt_limits({**RULES, "max_observations": 2, "confidence_cap_short": 0.4, "confidence_cap_long": 0.6})
    assert (tight["max_observations"], tight["short_window_levels"], tight["confidence_levels"]) == (
        2, '"low"', '"low" or "medium"')


def test_every_tunable_comes_from_the_policy():
    strict = {**RULES, "confidence_cap_long": 0.5, "max_evidence": 0}
    [rejected] = validate({"observations": [observation(confidence="high")]}, TRENDS, LEDGER, [], INFO, CLOCK,
                          rules=strict)[2]
    assert "evidence must list 1-0 items (it lists 1)" in rejected["reasons"]
    assert "confidence 'high' is above the cap 0.5" in rejected["reasons"]
    one = {**STORY, "max_active": 1}
    lines = reduce([], [{**observation(label=f"T{i}"), "team": "riv", "facts": [], "confidence": 0.5 + i / 10}
                        for i in range(2)], [], LEDGER, match_id="m", analysis_id="a1", clock=CLOCK, horizon=HORIZON,
                   rules=one)
    assert [s["status"] for s in lines] == ["dormant", "active"]


def test_the_shipped_policy_is_the_backends_seed():
    import json
    from pathlib import Path
    seed = Path(__file__).parents[2] / "user-backend" / "migrations" / "seeds" / "storyline-policy.json"
    if seed.exists():  # the engine image ships only its own files
        assert json.loads(seed.read_text()) == {k: getattr(POLICY, k) for k in ("analysis", "storylines", "repair",
                                                                                 "claims")}


def test_a_mismatched_citation_says_what_the_table_has():
    def reason(**evidence):
        item = observation(evidence=[{"indicator": "field_tilt", "team": "RIV", "window": "last15", "value": 0.78,
                                      **evidence}])
        return check(item)[2][0]["reasons"][0]
    assert "indicator 'field_tilt (/5min)' is not in the table; use the name before the colon" in \
        reason(indicator="field_tilt (/5min)")
    assert reason(window="half").endswith("(window 'half' has no such row; windows: last15)")
    assert reason(value=0.5).endswith("(the table shows 0.78)")



def test_claim_evidence_holds_every_factual_input_the_writer_saw():
    """A comparison drawn from the statistics table or a recap is checked against it."""
    from narrative_engine.analysis.validator import claim_state
    state = claim_state({"storylines": "S", "key_event_ledger": "", "match_trends": "T",
                         "game_state_statistics": "| Shots | 9 | 5 |", "combined_match_context": "R",
                         "match_events": "E", "trigger_reason": "Minute recap", "narrative_excerpts": "earlier text"})
    assert "The key event ledger:\nNone." in state and "| Shots | 9 | 5 |" in state
    assert "The minute recaps so far:\nR" in state and "The latest events:\nE" in state
    assert state.endswith("This step was triggered by:\nMinute recap")
    assert "earlier text" not in state  # earlier narratives are not evidence
    assert "statistics" not in claim_state({"storylines": "S"})  # absent inputs add no section


def test_a_storyline_resolved_just_before_half_time_is_still_shown_after_kickoff():
    """`resolved_shown_minutes` counts Opta minutes, which run on across periods (the second half starts at 45)."""
    from narrative_engine.context.builder import ContextBuilder

    class Data:
        async def match_info(self, match_id):
            return INFO

        async def key_events(self, match_id, clock, second=59):
            return []

        async def trends_at(self, match_id, seq):
            return []

    lines = analyse([], [observation()])
    done = analyse(lines, resolve=[{"storyline": "sl:m:1", "outcome": "Riverside turned it into a goal."}],
                   clock=MatchClock(1, 44), n=2)
    shown = lambda clock: asyncio.run(ContextBuilder(Data(), None).story_variables(
        "m", (clock, 0), 1, done, None))["storylines"]
    window = STORY["resolved_shown_minutes"]
    assert "Riverside squeeze the pitch" in shown(MatchClock(2, 44 + window))
    assert "Riverside squeeze the pitch" not in shown(MatchClock(2, 45 + window))
