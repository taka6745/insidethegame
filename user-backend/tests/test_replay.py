import asyncio
from types import SimpleNamespace

import pytest

from backend.agents.question import replay_draft
from backend.agents.replay import ReplayDecision, fallback, finish, json_object
from backend.agents.replay_fixture import FixtureReplayAgent, is_replay
from backend.adapters.hls_media import HlsMedia, parse_segments
from backend.services.replay import ReplayBuilder, ReplayTools
from backend.services.replay_clips import ReplayPlanError

PLAYERS = [{"id": "chelsea-1", "name": "Cole Palmer"}, {"id": "manutd-7", "name": "Bruno Fernandes"}]
TEAMS = [{"id": "chelsea", "name": "Chelsea"}, {"id": "manutd", "name": "Manchester United"}]


def row(identifier, kind, at, *, period=1, team="chelsea", player="chelsea-1", outcome=None, possession=1, **q):
    return {"event_id": identifier, "revision": 1, "event_type": kind, "team_id": team, "player_id": player,
            "period": period, "match_time_seconds": int(at), "video_seconds": float(at), "outcome": outcome,
            "possession_id": possession, "qualifiers": q}


HISTORY = [
    row("p1", "period_start", 0, team=None, player=None),
    row("e1", "pass", 60, outcome="failure", bodyPart="head"),
    row("e2", "interception", 61, team="manutd", player="manutd-7", possession=2),
    row("e3", "shot", 300, outcome="saved", bodyPart="head", situation="regular_play"),
    row("e4", "goal", 900, team="manutd", player="manutd-7", possession=3, bodyPart="right_foot"),
    row("e5", "touch", 901, bodyPart="head"),
    row("p2", "period_end", 2800, team=None, player=None),
    row("q1", "period_start", 2800, period=2, team=None, player=None),
    row("e6", "shot", 3000, period=2, outcome="off_target"),
]


class Matches:
    def __init__(self, rows):
        self.rows = rows

    async def events(self, snapshot, offset=0, limit=100, **unused):
        page = self.rows[offset:offset + limit]
        return {"items": page, "has_more": offset + limit < len(self.rows), "complete": True}


class Narratives:
    async def read(self, snapshot, operation, **filters):
        if operation == "key_moments":
            return {"items": [{"id": "km-goal", "rank": 1, "title": "15′ Fernandes scores", "period": 1,
                               "event_ids": ["e4"], "start_video_seconds": 880.0, "end_video_seconds": 915.0}]}
        return {"items": [{"id": "half-1", "tier": "half", "period": 1, "summary": "United led at the break."}]}


def tools(rows=HISTORY):
    return ReplayTools(SimpleNamespace(id="s"), Matches(rows), Narratives(), PLAYERS, TEAMS)


def run(coroutine):
    return asyncio.run(coroutine)


def test_find_events_filters_qualifiers_and_skips_contacts():
    toolkit = tools()
    found = run(toolkit.find_events(player_id="chelsea-1", qualifiers={"bodyPart": "head"}))
    assert [r["id"] for r in found["listed"]] == ["e1", "e3"]
    assert found["listed"][1]["minute"] == "6′" and found["complete_list"]
    assert toolkit.cited == {"e1", "e3"}


def test_absent_flag_is_false_so_keeper_saves_exclude_blocks():
    rows = [row("s1", "save", 10), row("s2", "save", 20, defensiveBlock=True)]
    found = run(tools(rows).find_events(event_types=["save"], qualifiers={"defensiveBlock": False}))
    assert [r["id"] for r in found["listed"]] == ["s1"]


def test_plan_json_is_taken_from_a_wrapped_model_reply():
    text = 'Here it is:\n```json\n{"status":"answer","text":"None yet."}\n```'
    assert ReplayDecision.model_validate_json(json_object(text)).text == "None yet."
    with pytest.raises(ValueError):
        json_object("Function invocation limit reached.")
    many = [{"source_id": f"e{i}", "kind": "event"} for i in range(50)]
    assert len(ReplayDecision(status="answer", text="Passes.", items=many).items) == 36


def test_uncaptioned_items_get_plain_captions_from_evidence():
    toolkit = tools()
    run(toolkit.find_events(event_types=["shot"]))
    run(toolkit.key_moments())
    assert toolkit.caption("e3", "event") == "6′ Cole Palmer shot saved"
    assert toolkit.caption("km-goal", "key_moment") == "15′ Fernandes scores"


def test_more_ids_become_captioned_items_only_when_cited():
    toolkit = tools()
    run(toolkit.find_events(event_types=["shot"]))
    decision = finish(ReplayDecision(status="answer", text="Shots.", more_ids=["e3", "e3", "e6", "invented"]), toolkit)
    assert [(i.source_id, i.caption) for i in decision.items] == [("e3", "6′ Cole Palmer shot saved"),
                                                                  ("e6", "51′ Cole Palmer shot off target")]


def test_broad_answers_with_a_refine_offer_keep_one_page():
    toolkit = tools([row(f"p{i}", "pass", 10 + i) for i in range(40)])
    run(toolkit.find_events(event_types=["pass"]))
    decision = finish(ReplayDecision(status="answer", text="Too many.", refine_offer="One half?",
                                     more_ids=[f"p{i}" for i in range(36)]), toolkit)
    assert len(decision.items) == 12


def test_absent_player_and_unknown_filter_are_unavailable():
    toolkit = tools()
    assert run(toolkit.find_events(player_id="kylian-mbappe"))["unavailable"]
    assert run(toolkit.find_events(qualifiers={"xG": "0.5"}))["unavailable"]


def test_sequences_derive_unrecorded_concepts_and_record_definition():
    toolkit = tools()
    found = run(toolkit.find_sequences({"event_types": ["pass"], "outcome": "failure"},
                                       {"event_types": ["interception"]}, 3, "opponent"))
    assert [r["id"] for r in found["listed"]] == ["e2"] and found["derived"]
    assert toolkit.derived["within_seconds"] == 3
    assert run(toolkit.find_sequences({}, {}, 60, "same"))["unavailable"]


def test_builder_rejects_uncited_evidence_and_cuts_within_periods():
    toolkit = tools()
    run(toolkit.find_events(event_types=["shot", "goal"]))
    items = [{"source_id": "e4", "kind": "event", "caption": "Goal", "lead_in": "normal"},
             {"source_id": "e3", "kind": "event", "caption": "Header saved", "lead_in": "normal"}]
    built = ReplayBuilder().build(toolkit, items)
    assert [(c["start"], c["end"]) for c in built["clips"]] == [(294.0, 303.0), (890.0, 902.0)]
    assert built["playlist"] is None and not built["truncated"]
    with pytest.raises(ReplayPlanError):
        ReplayBuilder().build(toolkit, [{**items[0], "source_id": "e5"}])


def test_builder_never_cuts_past_the_observed_prefix():
    toolkit = tools(HISTORY[:5])  # Observed up to the goal at 900 s.
    run(toolkit.find_events(event_types=["goal"]))
    built = ReplayBuilder().build(
        toolkit, [{"source_id": "e4", "kind": "event", "caption": "Goal", "lead_in": "normal"}])
    assert built["clips"][0]["end"] == 900.0


def test_builder_never_cuts_past_published_segments_and_requires_history(tmp_path):
    media, published = tmp_path / "media.m3u8", tmp_path / "live"
    media.write_text("#EXTM3U\n" + "".join(f"#EXTINF:300.0,\ns{i}.ts\n" for i in range(4)))
    published.mkdir()
    # Published through 900 s; the goal at 900 s needs footage after it.
    (published / "live.m3u8").write_text("#EXTM3U\n" + "".join(f"#EXTINF:300.0,\ns{i}.ts\n" for i in range(3)))
    toolkit = tools()
    run(toolkit.find_events(event_types=["goal"]))
    builder = ReplayBuilder(HlsMedia(parse_segments(media.read_text()), published_dir=str(published)))
    assert builder.media.published_edge() == 900.0
    item = {"source_id": "e4", "kind": "event", "caption": "Goal", "lead_in": "normal"}
    built = builder.build(toolkit, [item])
    assert built["clips"][0]["end"] == 900.0
    # Replays seek the continuous published stream: playlist times are match video times.
    assert built["playlist"] == "/media/hls/live.m3u8"
    assert (built["clips"][0]["playlist_start"], built["clips"][0]["playlist_end"]) == (890.0, 900.0)
    assert built["clips"][0]["marks"] == [900.0]
    unloaded = tools()
    unloaded.cited.add("e4")
    with pytest.raises(ReplayPlanError):
        builder.build(unloaded, [item])


def test_saved_bound_keeps_page_assignment_as_the_match_moves_on():
    toolkit = tools()
    run(toolkit.find_events(event_types=["shot", "goal"]))
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
    unknown = run(toolkit.find_events(event_types=["red_card"]))
    assert unknown["unavailable"] and "shot" in unknown["event_types"]
    assert not run(tools(HISTORY[:4]).find_events(event_types=["goal"])).get("unavailable")  # Valid before any goal.
    empty = run(toolkit.find_events(event_types=["shot"], outcome="post"))
    assert empty["total"] == 0 and empty["outcomes"] == ["off_target", "saved"]


def test_refine_offers_on_short_lists_do_not_cut_them():
    toolkit = tools([row(f"p{i}", "pass", 10 + i) for i in range(20)])
    run(toolkit.find_events(event_types=["pass"]))
    decision = finish(ReplayDecision(status="answer", text="Passes.", refine_offer="One half?",
                                     more_ids=[f"p{i}" for i in range(20)]), toolkit)
    assert len(decision.items) == 20


def test_uncited_items_are_dropped_not_fatal_and_recent_lists_notable_events():
    toolkit = tools()
    run(toolkit.find_events(event_types=["shot"]))
    decision = finish(ReplayDecision(status="answer", text="Shots.", items=[
        {"source_id": "e3", "kind": "event"}, {"source_id": "invented", "kind": "event"}]), toolkit)
    assert [i.source_id for i in decision.items] == ["e3"]
    recent = run(tools().recent(10))  # Latest observed is 3000 s: shots after 2400 s.
    assert [r["id"] for r in recent["listed"]] == ["e6"]


def test_unfinished_plans_fall_back_to_the_latest_search():
    toolkit = tools()
    with pytest.raises(ValueError):
        fallback(toolkit)
    run(toolkit.find_events(event_types=["shot"]))
    decision = finish(fallback(toolkit), toolkit)
    assert [i.source_id for i in decision.items] == ["e3", "e6"] and decision.text == "2 matching moments so far."


def test_a_plan_whose_clips_are_all_uncited_answers_from_its_latest_search():
    toolkit = tools()
    run(toolkit.find_events(event_types=["shot"]))
    decision = finish(ReplayDecision(status="answer", text="Here are the passes that led to goals.",
                                     items=[{"source_id": "invented", "kind": "event"}]), toolkit)
    assert [i.source_id for i in decision.items] == ["e3", "e6"] and "passes" not in decision.text


def test_a_capped_list_states_how_many_it_shows():
    toolkit = tools([row(f"p{i}", "pass", 10 + i) for i in range(40)])
    run(toolkit.find_events(event_types=["pass"]))
    decision = finish(ReplayDecision(status="answer", text="40 passes.", more_ids=[f"p{i}" for i in range(40)]), toolkit)
    assert len(decision.items) == 36 and decision.text.endswith("Showing the 36 most relevant of 40.")


def test_match_state_tells_the_agent_when_so_far_no_longer_applies():
    assert run(tools(HISTORY[:6]).match_state()) == "live"
    assert run(tools(HISTORY[:7]).match_state()) == "half-time"
    assert run(tools(HISTORY + [row("q2", "period_end", 5500, period=2, team=None, player=None)]).match_state()) == "finished"
