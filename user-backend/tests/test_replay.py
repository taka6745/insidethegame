import asyncio
from types import SimpleNamespace

import pytest

from backend.agents.question import replay_draft
from backend.agents.replay import ReplayDecision, fallback, finish, json_object
from benchmarks.doubles.replay_agent import FixtureReplayAgent, is_replay
from backend.adapters.hls_media import HlsMedia, parse_segments
from backend.services.replay import ReplayBuilder, ReplayTools
from backend.services.replay_clips import ReplayPlanError
from benchmarks.doubles.config import seeded

PLAYERS = [{"id": "riverton-1", "name": "Kai Ashworth"}, {"id": "forgeham-7", "name": "Theo Marchetti"}]
TEAMS = [{"id": "riverton", "name": "Riverton Rovers"}, {"id": "forgeham", "name": "Forgeham United"}]


def row(identifier, kind, at, *, period=1, team="riverton", player="riverton-1", result="success", possession=1,
        bodypart=None, shot_outcome=None, start_zone="middle_third", end_zone="middle_third"):
    """One SPADL action as match_data.actions serves it (SpadlAction.row)."""
    return {"id": identifier, "action_type": kind, "result": result, "team_id": team, "player_id": player,
            "period": period, "match_time_seconds": int(at), "video_seconds": float(at), "possession_id": possession,
            "bodypart": bodypart or "foot", "bodypart_observed": bodypart is not None, "shot_outcome": shot_outcome,
            "start_zone": start_zone, "end_zone": end_zone}


HISTORY = [
    row("e1", "pass", 60, result="fail", bodypart="head"),
    row("e2", "interception", 61, team="forgeham", player="forgeham-7", possession=2),
    row("e3", "shot", 300, result="fail", bodypart="head", shot_outcome="saved", end_zone="opp_box"),
    row("e4", "shot", 900, team="forgeham", player="forgeham-7", possession=3, bodypart="foot_right", shot_outcome="goal"),
    row("e5", "dribble", 901),
    row("e6", "shot", 3000, period=2, result="fail", shot_outcome="off_target"),
]
PERIODS = {1: (0.0, 2800.0), 2: (2800.0, None)}


class Matches:
    def __init__(self, rows, periods=PERIODS, cards=()):
        self.rows, self.period_rows, self.card_rows = rows, periods, list(cards)

    async def actions(self, snapshot, offset=0, limit=100, **unused):
        page = self.rows[offset:offset + limit]
        return {"items": page, "has_more": offset + limit < len(self.rows), "complete": True}

    async def cards(self, snapshot):
        return self.card_rows

    async def periods(self, snapshot):
        return self.period_rows


class Narratives:
    async def read(self, snapshot, operation, **filters):
        if operation == "key_moments":
            return {"items": [{"id": "km-goal", "rank": 1, "title": "15′ Marchetti scores", "period": 1,
                               "event_ids": ["e4"], "start_video_seconds": 880.0, "end_video_seconds": 915.0}]}
        return {"items": [{"id": "half-1", "tier": "half", "period": 1, "summary": "United led at the break."}]}


def tools(rows=HISTORY, periods=PERIODS, cards=()):
    return ReplayTools(SimpleNamespace(id="m:1", match_id="m", seq=1), Matches(rows, periods, cards), Narratives(), PLAYERS,
                       TEAMS, seeded("replay-timing"))


def run(coroutine):
    return asyncio.run(coroutine)


def test_find_events_filters_spadl_values_and_skips_carries():
    toolkit = tools()
    found = run(toolkit.find_events(player_id="riverton-1", bodyparts=["head"]))
    assert [r["id"] for r in found["listed"]] == ["e1", "e3"]
    assert found["listed"][1]["minute"] == "6′" and found["complete_list"]
    assert toolkit.cited == {"e1", "e3"}
    assert [r["id"] for r in run(toolkit.find_events(end_zones=["opp_box"]))["listed"]] == ["e3"]
    assert [r["id"] for r in run(toolkit.find_events(action_types=["dribble"]))["listed"]] == ["e5"]


def test_cards_are_searched_separately_and_second_yellows_count_as_both():
    cards = [{"id": "card:1", "colour": "yellow", "team_id": "forgeham", "player_id": "forgeham-7", "period": 1,
              "match_time_seconds": 100, "video_seconds": 100.0},
             {"id": "card:2", "colour": "second_yellow", "team_id": "forgeham", "player_id": "forgeham-7", "period": 2,
              "match_time_seconds": 3100, "video_seconds": 3100.0}]
    toolkit = tools(cards=cards)
    assert [r["id"] for r in run(toolkit.find_cards("yellow"))["listed"]] == ["card:1", "card:2"]
    assert [r["id"] for r in run(toolkit.find_cards("red"))["listed"]] == ["card:2"]
    assert run(toolkit.find_cards(None, period=1))["listed"][0]["type"] == "card"
    assert toolkit.caption("card:2", "event") == "52′ Theo Marchetti second yellow card"


def test_off_target_shot_is_never_captioned_saved():
    # Reported: a replay summary called an off-target shot "saved" because the keeper touched it.
    rows = [row("s1", "shot", 4469, period=2, result="fail", shot_outcome="off_target"),
            row("k1", "keeper_save", 4469, period=2, team="forgeham", player="forgeham-7"),
            row("s2", "shot", 4500, period=2, result="fail", shot_outcome="saved")]
    toolkit = tools(rows)
    listed = run(toolkit.find_events(action_types=["shot", "keeper_save"]))["listed"]
    assert listed[0]["shot_outcome"] == "off_target"  # The model sees the shot's own outcome.
    decision = finish(ReplayDecision(status="answer", text="Shots.", items=[
        {"source_id": "s1", "kind": "event", "caption": "75′ Ashworth shot saved"},
        {"source_id": "k1", "kind": "event", "caption": "75′ Marchetti saves"},
        {"source_id": "s2", "kind": "event", "caption": "76′ Ashworth shot saved"}]), toolkit)
    assert [i.caption for i in decision.items] == ["75′ Kai Ashworth shot off target", "75′ Marchetti saves",
                                                   "76′ Ashworth shot saved"]


def test_plan_json_is_taken_from_a_wrapped_model_reply():
    text = 'Here it is:\n```json\n{"status":"answer","text":"None yet."}\n```'
    assert ReplayDecision.model_validate_json(json_object(text)).text == "None yet."
    with pytest.raises(ValueError):
        json_object("Function invocation limit reached.")
    many = [{"source_id": f"e{i}", "kind": "event"} for i in range(50)]
    assert len(ReplayDecision(status="answer", text="Passes.", items=many).items) == 36


def test_uncaptioned_items_get_plain_captions_from_evidence():
    toolkit = tools()
    run(toolkit.find_events(action_types=["shot"]))
    run(toolkit.key_moments())
    assert toolkit.caption("e3", "event") == "6′ Kai Ashworth header shot saved"
    assert toolkit.caption("e1", "event") == "2′ Kai Ashworth headed failed pass"
    assert toolkit.caption("km-goal", "key_moment") == "15′ Marchetti scores"


def test_more_ids_become_captioned_items_only_when_cited():
    toolkit = tools()
    run(toolkit.find_events(action_types=["shot"]))
    decision = finish(ReplayDecision(status="answer", text="Shots.", more_ids=["e3", "e3", "e6", "invented"]), toolkit)
    assert [(i.source_id, i.caption) for i in decision.items] == [("e3", "6′ Kai Ashworth header shot saved"),
                                                                  ("e6", "51′ Kai Ashworth shot off target")]


def test_broad_answers_with_a_refine_offer_keep_one_page():
    toolkit = tools([row(f"p{i}", "pass", 10 + i) for i in range(40)])
    run(toolkit.find_events(action_types=["pass"]))
    decision = finish(ReplayDecision(status="answer", text="Too many.", refine_offer="One half?",
                                     more_ids=[f"p{i}" for i in range(36)]), toolkit)
    assert len(decision.items) == 12


def test_absent_player_and_unknown_filter_are_unavailable():
    toolkit = tools()
    assert run(toolkit.find_events(player_id="kylian-mbappe"))["unavailable"]
    assert run(toolkit.find_events(action_types=["xg"]))["unavailable"]
    assert run(toolkit.find_events(end_zones=["penalty_spot"]))["unavailable"]


def test_sequences_derive_unrecorded_concepts_and_record_definition():
    toolkit = tools()
    found = run(toolkit.find_sequences({"action_types": ["pass"], "results": ["fail"]},
                                       {"action_types": ["interception"]}, 3, "opponent"))
    assert [r["id"] for r in found["listed"]] == ["e2"] and found["derived"]
    assert toolkit.derived["within_seconds"] == 3
    assert toolkit.derived["description"] == "failed pass, then opponent interception within 3 s"
    assert run(toolkit.find_sequences({}, {}, 60, "same"))["unavailable"]


def test_builder_rejects_uncited_evidence_and_cuts_within_periods():
    toolkit = tools()
    run(toolkit.find_events(action_types=["shot"]))
    items = [{"source_id": "e4", "kind": "event", "caption": "Goal", "lead_in": "normal"},
             {"source_id": "e3", "kind": "event", "caption": "Header saved", "lead_in": "normal"}]
    built = ReplayBuilder().build(toolkit, items)
    assert [(c["start"], c["end"]) for c in built["clips"]] == [(294.0, 303.0), (890.0, 905.0)]
    assert built["playlist"] is None and not built["truncated"]
    with pytest.raises(ReplayPlanError):
        ReplayBuilder().build(toolkit, [{**items[0], "source_id": "e5"}])


def test_own_goal_clips_show_the_attack_and_say_who_it_counts_for():
    # United attack (possession 7 from 1000 s); a Riverton Rovers defender's single touch (possession 8) is the own goal.
    rows = [row("a1", "pass", 1000, team="forgeham", player="forgeham-7", possession=7),
            row("a2", "cross", 1012, team="forgeham", player="forgeham-7", possession=7),
            row("og", "bad_touch", 1014, result="owngoal", possession=8)]
    toolkit = tools(rows)
    run(toolkit.find_events(results=["owngoal"]))
    item = {"source_id": "og", "kind": "event", "caption": "Theo Marchetti goal", "lead_in": "move"}
    built = ReplayBuilder().build(toolkit, [item])
    assert built["clips"][0]["start"] == 999.0  # the United move, not the defender's one-touch possession
    # The model's caption named the wrong scorer: an own goal is always captioned from evidence.
    assert toolkit.checked_caption("og", "event", item["caption"]) == "17′ Kai Ashworth own goal (Forgeham United goal)"


def test_builder_never_cuts_past_the_observed_prefix():
    toolkit = tools(HISTORY[:4])  # Observed up to the goal at 900 s.
    run(toolkit.find_events(action_types=["shot"], results=["success"]))
    built = ReplayBuilder().build(
        toolkit, [{"source_id": "e4", "kind": "event", "caption": "Goal", "lead_in": "normal"}])
    assert built["clips"][0]["end"] == 900.0


def test_builder_never_cuts_past_published_segments_and_requires_history():
    class Media(HlsMedia):
        async def published_edge(self, match_id):
            return {"m": 900.0}.get(match_id, 0.0)  # The feed published through 900 s.
    toolkit = tools()
    run(toolkit.find_events(action_types=["shot"], results=["success"]))
    builder = ReplayBuilder(Media("http://feed/hls"))
    edge = run(builder.edge(toolkit.snapshot, True))
    assert edge == 900.0 and run(builder.edge(toolkit.snapshot, False)) is None
    item = {"source_id": "e4", "kind": "event", "caption": "Goal", "lead_in": "normal"}
    built = builder.build(toolkit, [item], edge=edge)
    assert built["clips"][0]["end"] == 900.0
    # Replays seek the match's continuous published stream: playlist times are match video times.
    assert built["playlist"] == "/media/hls/m/live.m3u8"
    assert (built["clips"][0]["playlist_start"], built["clips"][0]["playlist_end"]) == (890.0, 900.0)
    assert built["clips"][0]["marks"] == [900.0]
    # Every replay carries the reel's playback settings (replay-timing.playback, migrations/037).
    assert built["playback"] == toolkit.config.playback.model_dump()
    assert built["playback"]["transitions"]["asset"].startswith("/assets/")
    unloaded = tools()
    unloaded.cited.add("e4")
    with pytest.raises(ReplayPlanError):
        builder.build(unloaded, [item], edge=edge)


def test_saved_bound_keeps_page_assignment_as_the_match_moves_on():
    toolkit = tools()
    run(toolkit.find_events(action_types=["shot"]))
    item = {"source_id": "e6", "kind": "event", "caption": "Shot", "lead_in": "normal"}
    builder = ReplayBuilder()
    assert builder.build(toolkit, [item])["observed_until"] == 3000.0
    assert builder.build(toolkit, [item], until=2900.0)["clips"] == []  # Not playable when asked: stays off.


def test_fixture_agent_absent_player_offers_alternative():
    decision = run(FixtureReplayAgent().plan("show me all the headers by mbappe", {"players": PLAYERS}, tools()))
    assert decision.items == [] and "not in this match" in decision.text


def test_fixture_agent_shots_and_half_summary():
    shots = run(FixtureReplayAgent().plan("show me all the shots so far", {"players": PLAYERS}, tools()))
    assert [i.source_id for i in shots.items] == ["e3", "e4", "e6"]
    half = run(FixtureReplayAgent().plan("how did the first half go", {"players": PLAYERS}, tools()))
    assert half.text == "United led at the break."
    assert [(i.source_id, i.kind) for i in half.items] == [("km-goal", "key_moment")]
    draft = replay_draft(half)
    assert draft.answer_kind == "replay" and draft.replay_items[0].kind == "key_moment"


def test_replay_phrases_are_recognised():
    assert is_replay("Show me the goals") and is_replay("how did the second half go")
    assert not is_replay("how many shots")


def test_unknown_types_and_empty_searches_point_the_agent_at_valid_values():
    toolkit = tools()
    unknown = run(toolkit.find_events(action_types=["red_card"]))
    assert unknown["unavailable"] and "'shot'" in unknown["message"]
    goals = {"action_types": ["shot"], "results": ["success"]}
    assert not run(tools(HISTORY[:3]).find_events(**goals)).get("unavailable")  # Valid before any goal.
    empty = run(toolkit.find_events(action_types=["shot"], shot_outcomes=["post"]))
    assert empty["total"] == 0 and empty["results"] == ["fail", "success"]


def test_refine_offers_on_short_lists_do_not_cut_them():
    toolkit = tools([row(f"p{i}", "pass", 10 + i) for i in range(20)])
    run(toolkit.find_events(action_types=["pass"]))
    decision = finish(ReplayDecision(status="answer", text="Passes.", refine_offer="One half?",
                                     more_ids=[f"p{i}" for i in range(20)]), toolkit)
    assert len(decision.items) == 20


def test_uncited_items_are_dropped_not_fatal_and_recent_lists_notable_events():
    toolkit = tools()
    run(toolkit.find_events(action_types=["shot"]))
    decision = finish(ReplayDecision(status="answer", text="Shots.", items=[
        {"source_id": "e3", "kind": "event"}, {"source_id": "invented", "kind": "event"}]), toolkit)
    assert [i.source_id for i in decision.items] == ["e3"]
    recent = run(tools().recent(10))  # Latest observed is 3000 s: shots after 2400 s.
    assert [r["id"] for r in recent["listed"]] == ["e6"]


def test_unfinished_plans_fall_back_to_the_latest_search():
    toolkit = tools()
    with pytest.raises(ValueError):
        fallback(toolkit)
    run(toolkit.find_events(action_types=["shot"], results=["fail"]))
    decision = finish(fallback(toolkit), toolkit)
    assert [i.source_id for i in decision.items] == ["e3", "e6"] and decision.text == "2 matching moments so far."


def test_a_plan_whose_clips_are_all_uncited_answers_from_its_latest_search():
    toolkit = tools()
    run(toolkit.find_events(action_types=["shot"], results=["fail"]))
    decision = finish(ReplayDecision(status="answer", text="Here are the passes that led to goals.",
                                     items=[{"source_id": "invented", "kind": "event"}]), toolkit)
    assert [i.source_id for i in decision.items] == ["e3", "e6"] and "passes" not in decision.text


def test_events_shown_in_the_input_and_key_moment_events_are_citable():
    toolkit = tools()
    run(toolkit.match_state())
    toolkit.cite_shown({"compact": {"tail": [{"id": "e6"}], "key_events": [{"id": "unknown"}]}})
    decision = finish(ReplayDecision(status="answer", text="That shot.",
                                     items=[{"source_id": "action:e6", "kind": "event"}]), toolkit)
    assert [i.source_id for i in decision.items] == ["e6"]
    run(toolkit.key_moments())  # km-goal lists e4
    decision = finish(ReplayDecision(status="answer", text="The goal.", items=[{"source_id": "e4", "kind": "event"},
                                                                              {"source_id": "unknown", "kind": "event"}]),
                      toolkit)
    assert [i.source_id for i in decision.items] == ["e4"]


def test_a_capped_list_states_how_many_it_shows():
    toolkit = tools([row(f"p{i}", "pass", 10 + i) for i in range(40)])
    run(toolkit.find_events(action_types=["pass"]))
    decision = finish(ReplayDecision(status="answer", text="40 passes.", more_ids=[f"p{i}" for i in range(40)]), toolkit)
    assert len(decision.items) == 36 and decision.text.endswith("Showing the 36 most relevant of 40.")


def test_match_state_tells_the_agent_when_so_far_no_longer_applies():
    assert run(tools(HISTORY[:5], {1: (0.0, None)}).match_state()) == "live"
    assert run(tools(HISTORY[:5], {1: (0.0, 2800.0)}).match_state()) == "half-time"
    assert run(tools(periods={1: (0.0, 2800.0), 2: (2800.0, 5500.0)}).match_state()) == "finished"


def test_the_sting_cut_happens_while_it_fully_covers_the_picture():
    from pydantic import ValidationError
    from backend.models.config import Transitions
    seed = seeded("replay-timing").playback.transitions.model_dump()
    for cut, fade in ((0.2, 0.3), (2.2, 0.3)):  # before the fade in ends, after the fade out starts
        with pytest.raises(ValidationError):
            Transitions.model_validate({**seed, "cut_seconds": cut, "fade_seconds": fade})
    assert Transitions.model_validate({**seed, "cut_seconds": 0.3, "fade_seconds": 0.3}).cut_seconds == 0.3


def test_events_behind_a_location_stat_can_be_found_for_a_replay():
    """PLAN.md §12 M14: 'show me those take-ons in their own half' searches with the stat's location bound."""
    rows = [{**row("t1", "take_on", 100), "start_x": 30.0}, {**row("t2", "take_on", 200), "start_x": 70.0},
            {**row("p1", "keeper_punch", 300, team="forgeham", player="forgeham-7"), "start_x": 5.0}]
    toolkit = tools(rows)
    found = run(toolkit.find_events(action_types=["take_on"], locations=[{"field": "start_x", "lte": 52.5}]))
    assert [item["id"] for item in found["listed"]] == ["t1"]
    assert [item["id"] for item in run(toolkit.find_events(action_types=["keeper_punch"]))["listed"]] == ["p1"]
