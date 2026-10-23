"""Story follows: the topic source, the trigger rules (prefilter, gap, fire rule) and the pipeline over the whole
Riverton Rovers–Forgeham United recording (synthetic) with fake agents and a fake decision model. Live and as a backlog the
decision model gets the same states and questions and the follow narratives are the same; a restart reuses the
stored decision instead of asking again; a purge removes the follow documents."""
import asyncio
import copy
import hashlib
import re
from pathlib import Path

import pytest

import riverton_forgeham
from support import BASE, Backend, EtlAsOf, client, spells_at, trends_at
from narrative_engine.agents.prompt_source import PLACEHOLDER, PROMPTS, ROLES, shipped
from narrative_engine.api import schema
from narrative_engine.context.render import MatchInfo
from narrative_engine.core.models import parse_notification
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.decisions import Answer, DecisionError, Noul, Score
from doubles.fake_agents import FakeAgents
from doubles.fake_decisions import FakeDecisions
from doubles.follows import CONFIG, StaticTopics, topic
from doubles.targets import StaticTargets, default_targets
from narrative_engine.follows import pipeline
from narrative_engine.follows.topics import HttpTopicSource
from narrative_engine.service import Router
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink

MATCH = riverton_forgeham.MATCH
INFO = MatchInfo.from_ma1({"matchId": "m", "contestant": [
    {"id": "che", "name": "Riverton Rovers", "code": "RVR", "position": "home", "lineup": [{"playerId": "p9", "name": "Cole"}]},
    {"id": "mun", "name": "Forgeham United", "code": "FGU", "position": "away"}]})


def targets_doc(revision, topics):
    return {"schema_version": 1, "match_id": "demo", "revision": revision, "config_revision": 1,
            **copy.deepcopy(CONFIG), "topics": topics}


def test_topics_revalidate_with_the_etag_and_a_document_without_a_tunable_is_refused():
    one = topic("topic:00000000000000a1", "team", ["home:casual"], team_id="che", label="Riverton Rovers")
    backend = Backend({"/matches/demo/subscription-targets": targets_doc(4, [one])})
    source = HttpTopicSource(BASE, client(backend), max_age=0)
    first = asyncio.run(source.current("demo"))
    again = asyncio.run(source.current("demo"))
    assert (first.revision, first.config_revision, again.topics) == (4, 1, first.topics)
    assert first.topics[0]["spec"]["team_id"] == "che" and first.config["limits"]["pivotal_key_types"]
    assert backend.requests == [("/matches/demo/subscription-targets", None),
                                ("/matches/demo/subscription-targets", '"4"')]
    broken = targets_doc(5, [])
    del broken["limits"]["pivotal_key_types"]
    other = HttpTopicSource(BASE, client(Backend({"/matches/demo/subscription-targets": broken})))
    with pytest.raises(KeyError):
        asyncio.run(other.current("demo"))


def test_the_follow_prompts_are_engine_roles_and_byte_copies_of_the_backend_seeds():
    assert {"subscription-decision", "subscription-author"} <= set(ROLES)
    seeds = Path(__file__).parents[2] / "user-backend" / "migrations" / "prompts"
    if seeds.exists():  # the engine image ships only its own files
        for role in ("subscription-decision", "subscription-author"):
            assert (seeds / f"{role}.txt").read_bytes() == (PROMPTS / f"{shipped(role).label}.txt").read_bytes()


def line(n, team=None, status="active"):
    return {"id": f"sl:m:{n}", "label": f"Line {n}", "team": team, "status": status}


LINES = {s["id"]: s for s in (line(1, "che"), line(2), line(3, "mun", "resolved"))}
TOPICS = {"team": topic("t-team", "team", ["b"], team_id="che"),
          "player": topic("t-player", "player", ["b"], player_id="p9", team_id="che"),
          "line1": topic("t-line1", "storyline", ["b"], storyline_id="sl:m:1"),
          "line2": topic("t-line2", "storyline", ["b"], storyline_id="sl:m:2"),
          "line3": topic("t-line3", "storyline", ["b"], storyline_id="sl:m:3"),
          "theme": topic("t-theme", "theme", ["b"], focus="set pieces"),
          "late": topic("t-late", "team", ["b"], created_seq=500, team_id="che")}


def candidates(entities, seq=100):
    return sorted(k for k, t in TOPICS.items() if pipeline.is_candidate(t, entities, LINES, seq))


def test_the_prefilter_keeps_the_topics_the_update_involves():
    goal = {"keyType": "Goal", "contestantId": "mun", "playerId": "m2", "id": 1}
    # A United goal involves Riverton Rovers' follows too, and every open storyline; not a player who is not in it.
    assert candidates(pipeline.update_entities("keyEvent", INFO, goal)) == ["line1", "line2", "team", "theme"]
    penalty = {"keyType": "PenaltyAwarded", "detail": "conceded", "contestantId": "che", "playerId": "p9", "id": 2}
    assert candidates(pipeline.update_entities("keyEvent", INFO, penalty)) == \
        ["line1", "line2", "player", "team", "theme"]
    minute = [{"contestantId": "che", "playerId": "p9"}, {"contestantId": "che", "playerId": None}]
    assert candidates(pipeline.update_entities("scheduled", INFO, events=minute)) == \
        ["line1", "line2", "player", "team", "theme"]
    assert candidates(pipeline.update_entities("scheduled", INFO, events=[])) == []  # an empty minute
    moved = pipeline.update_entities("storylineTurn", INFO, moved=[LINES["sl:m:3"]])
    assert candidates(moved) == ["line3", "theme"]  # the analysis resolved it
    moved = pipeline.update_entities("storylineTurn", INFO, moved=[LINES["sl:m:1"]])
    assert candidates(moved) == ["line1", "team", "theme"]  # a Riverton Rovers storyline involves a Riverton Rovers follow
    assert "team" in candidates(pipeline.update_entities("storylineTurn", INFO, moved=[LINES["sl:m:2"]]))
    everything = ["line1", "line2", "line3", "player", "team", "theme"]
    assert candidates(pipeline.update_entities("fullTime", INFO)) == everything
    assert candidates(pipeline.update_entities("fullTime", INFO), seq=500) == ["late"] + everything
    gone = topic("t-gone", "storyline", ["b"], storyline_id="sl:m:9")  # not opened by this update's analysis
    assert not pipeline.is_candidate(gone, {"all": True}, LINES, 100)


def test_the_gap_is_match_time_in_one_period_and_pivotal_moments_bypass_it():
    limits = CONFIG["limits"]
    assert pipeline.within_gap([1, 10, 30], [1, 11, 29], limits)
    assert not pipeline.within_gap([1, 10, 30], [1, 11, 30], limits) and not pipeline.within_gap(None, [1, 1, 0], limits)
    assert not pipeline.within_gap([1, 46, 50], [2, 45, 5], limits)  # a new period
    assert pipeline.pivotal("keyEvent", {"keyType": "RedCard"}, limits) and pipeline.pivotal("halfTime", None, limits)
    assert not pipeline.pivotal("keyEvent", {"keyType": "Substitution"}, limits)
    assert not pipeline.pivotal("keyEvent", {"keyType": "Goal"}, {**limits, "pivotal_key_types": []})


def test_one_score_per_candidate_novelty_only_with_a_last_narrative_and_the_fire_rule():
    cands = [TOPICS["team"], TOPICS["theme"]]
    asked, keys = pipeline.questions(cands, CONFIG, {"t-team": "Riverton Rovers pressed high."}, INFO, LINES)
    assert list(asked) == ["t1", "t1n", "t2"] and isinstance(asked["t1n"], Noul) and isinstance(asked["t2"], Score)
    assert "the team Riverton Rovers" in asked["t1"].instructions and '"Riverton Rovers pressed high."' in asked["t1n"].instructions
    assert "\"set pieces\"" in asked["t2"].instructions and asked["t2"].levels == tuple(CONFIG["decision"]["levels"])
    assert "set pieces" not in asked["t1"].instructions + asked["t1n"].instructions  # each focus in its own questions

    def fire(score, confidence=0.9, novelty=None, config=CONFIG):
        answers = {"t1": Answer("score", score=score, confidence=confidence), "t2": Answer("score", score=0.0,
                                                                                           confidence=1.0)}
        if novelty is not None:
            answers["t1n"] = Answer("noul", probability=novelty)
        return pipeline.verdicts(cands, answers, keys, config)["t-team"]["fired"]
    assert fire(2.0, novelty=0.5) and fire(3.0, novelty=0.9)
    assert not fire(1.4, novelty=0.9) and not fire(2.0, 0.2, novelty=0.9) and not fire(2.0, novelty=0.4)
    assert fire(1.95, novelty=0.9)  # Decision-1's expected level counts at its nearest level, like the clip score
    assert not fire(3.0)  # novelty asked but declined: a no
    off = {**CONFIG, "novelty": {**CONFIG["novelty"], "enabled": False}}
    asked, keys = pipeline.questions(cands, off, {"t-team": "x"}, INFO, LINES)
    assert "t1n" not in asked and fire(2.0, config=off)
    first = pipeline.verdicts(cands, {"t2": Answer("score", score=2.0, confidence=0.3)}, {"t2": ("t-theme", "score")},
                              CONFIG)
    assert first["t-theme"]["fired"] and not first["t-team"]["fired"]  # no last narrative: no novelty question


def test_a_key_event_asks_the_clip_score_in_the_same_call_and_a_clip_fires_its_topic():
    goal = {"keyType": "Goal", "contestantId": "che"}
    assert pipeline.clip_moment("keyEvent", goal, CONFIG)
    assert not pipeline.clip_moment("scheduled", None, CONFIG)
    assert not pipeline.clip_moment("keyEvent", goal, {**CONFIG, "clips": {**CONFIG["clips"], "key_types": []}})
    cands = [TOPICS["team"], TOPICS["theme"]]
    asked, keys = pipeline.questions(cands, CONFIG, {}, INFO, LINES, clip=True)
    assert list(asked) == ["t1", "t1c", "t2", "t2c"] and asked["t1c"].levels == tuple(CONFIG["clips"]["levels"])
    assert "the team Riverton Rovers" in asked["t1c"].instructions and "set pieces" not in asked["t1c"].instructions
    assert "t1c" not in pipeline.questions(cands, CONFIG, {}, INFO, LINES)[0]

    def verdict(clip_score, confidence=0.9, score=0.0):
        answers = {"t1": Answer("score", score=score, confidence=0.9),
                   "t1c": Answer("score", score=clip_score, confidence=confidence)}
        return pipeline.verdicts(cands, answers, keys, CONFIG)["t-team"]
    assert verdict(3.0) == {"score": 0.0, "confidence": 0.9, "novelty": None, "clip": True, "fired": True}
    assert not verdict(2.0)["clip"] and not verdict(2.0)["fired"]  # below clips.min_level
    assert verdict(2.74)["clip"] and not verdict(2.4)["clip"]  # an expected level counts at its nearest level
    assert not verdict(3.0, confidence=0.2)["clip"]                 # below clips.min_confidence
    assert verdict(2.0, score=3.0) == {"score": 3.0, "confidence": 0.9, "novelty": None, "clip": False,
                                       "fired": True}


def test_a_clip_on_topic_clips_without_the_clip_question():
    """`clips.always_for` (041): a topic of that kind is clip-on from creation; others are still asked."""
    config = {**CONFIG, "clips": {**CONFIG["clips"], "always_for": ["team"]}}
    cands = [TOPICS["team"], TOPICS["theme"]]
    asked, keys = pipeline.questions(cands, config, {}, INFO, LINES, clip=True)
    assert list(asked) == ["t1", "t2", "t2c"]
    answers = {"t1": Answer("score", score=0.0, confidence=0.9), "t2": Answer("score", score=0.0, confidence=0.9),
               "t2c": Answer("score", score=0.0, confidence=0.9)}
    out = pipeline.verdicts(cands, answers, keys, config, clip=True)
    assert out["t-team"]["clip"] and out["t-team"]["fired"] and not out["t-theme"]["clip"]
    assert not pipeline.verdicts(cands, answers, pipeline.questions(cands, config, {}, INFO, LINES)[1], config)[
        "t-team"]["clip"]  # not a clip moment: nothing clips


def rule(key, question, state):
    """A deterministic stand-in: answers are a hash of the whole state and question, so equal answers mean
    equal inputs."""
    if not key.startswith("t"):  # the authors' claim checks: no unsupported claims (tested in test_storylines)
        return 0.0
    h = int(hashlib.sha256(f"{key}\n{question.instructions}\n{state}".encode()).hexdigest(), 16)
    return h % 4 if isinstance(question, Score) else (h % 10) / 10 + 0.05


THEME_FROM = next(seq for body, seq in riverton_forgeham.timeline() if body.get("periodId") == 1
                  and body.get("timeMin") == 30)


def follow_topics():
    return [topic("topic:00000000000000c1", "team", ["home:simple", "home:casual"], team_id="riverton",
                  label="Riverton Rovers", focus="their high press"),
            topic("topic:00000000000000c2", "player", ["home:casual"], player_id="forgeham-2", team_id="forgeham"),
            topic("topic:00000000000000c3", "storyline", ["home:simple"], storyline_id=f"sl:{MATCH}:1"),
            topic("topic:00000000000000c4", "theme", ["home:experienced"], created_seq=THEME_FROM,
                  focus="Riverton Rovers' set pieces"),
            topic("topic:00000000000000c5", "team", ["away:casual"], team_id="forgeham")]  # a disabled bucket


class FlakyPublisher(MemorySink):
    """Fails the first follow narrative it is given (stored, not sent), then works. `on`: only one of that trigger."""
    failed, on = False, None

    async def publish(self, narrative):
        if narrative.kind == "subscription" and not self.failed and self.on in (None, narrative.trigger.type):
            self.failed = True
            raise ConnectionError("publish failed")
        await super().publish(narrative)


def run(backlog=False, crash=False, change=None, decide=rule, config=None):
    data = EtlAsOf(riverton_forgeham.REPLAY, stats=riverton_forgeham.golden_stats(), actions_path=riverton_forgeham.ACTIONS,
                   keys=riverton_forgeham.key_rows(), trends=trends_at, spells=spells_at)
    store, topics = MemoryStore(), StaticTopics(follow_topics(), config)
    sink = FlakyPublisher(store) if crash else MemorySink(store)
    if isinstance(crash, str):
        sink.on = crash
    asked = []

    def engine():
        model = FakeDecisions(rule=decide)
        asked.append(model)
        return MatchOrchestrator(MATCH, data, FakeAgents(), store, sink, targets=StaticTargets(default_targets()[:3]),
                                 follows=topics, decisions=model)
    orchestrator = engine()

    async def go():
        nonlocal orchestrator
        for i, (body, seq) in enumerate(riverton_forgeham.timeline()):
            if change and i == change[0]:
                topics.set(change[1])
            data.limit = None if backlog else seq
            await orchestrator.record(parse_notification(body))
            if not backlog:
                try:
                    await orchestrator.work()
                except ConnectionError:
                    orchestrator = engine()  # a restart: a new process from the stored checkpoint
        data.limit = None
        await orchestrator.work()
    asyncio.run(go())
    calls = [c for model in asked for c in model.calls]
    return {"store": store, "calls": calls, "asked": asked, "sink": sink,
            "decisions": asyncio.run(store.decisions(MATCH)),
            "follows": asyncio.run(store.subscription_narratives(MATCH))}


@pytest.fixture(scope="module")
def runs():
    return run(), run(backlog=True)


def strip(docs):
    return [{k: v for k, v in d.items() if k != "createdAt"} for d in docs]


def key(n):
    return n.id, n.stepId, n.trigger, n.text, n.eventSeq, n.analysisId, n.storylineIds, n.decision, n.timeSec


def test_live_and_backlog_ask_the_same_questions_and_write_the_same_follow_narratives(runs):
    live, backlog = runs
    states = lambda r: [(state, sorted(q)) for state, q in r["calls"]]
    assert states(live) == states(backlog)
    assert strip(live["decisions"]) == strip(backlog["decisions"])
    assert [key(n) for n in live["follows"]] == [key(n) for n in backlog["follows"]]


def test_follow_decisions_cover_every_trigger_and_fire_by_the_rule(runs):
    live, _ = runs
    decisions = live["decisions"]
    kinds = {d["triggerType"] for d in decisions}
    assert kinds == {"keyEvent", "scheduled", "storylineTurn", "halfTime", "fullTime"}
    assert len([d for d in decisions if d["triggerType"] == "keyEvent"]) == len(riverton_forgeham.key_rows())
    ends = [d for d in decisions if d["triggerType"] in ("halfTime", "fullTime")]
    # Period ends: every candidate gets the wrap-up (limits.period_end_wrap_up), without a question.
    assert ends and all(d["fired"] == d["candidates"] and d["questions"] == 0 and d["model"] is None for d in ends)
    assert all(v["wrapUp"] for d in ends for v in d["verdicts"].values())
    asked = [d for d in decisions if d["candidates"] and d not in ends]
    assert asked and all(d["questions"] >= len(d["candidates"]) and d["model"] == "fake" for d in asked)
    assert any(d["fired"] for d in decisions) and any(d["candidates"] and not d["fired"] for d in decisions)
    assert any("gap" in d["skipped"].values() for d in decisions)
    for d in asked:
        for topic_id in d["fired"]:
            v = d["verdicts"][topic_id]
            assert v["clip"] or (v["score"] >= 2 and v["confidence"] >= 0.5
                                 and (v["novelty"] is None or v["novelty"] >= 0.5))
    # Clips are asked only on key events of `clips.key_types`, and one fired somewhere in the match.
    assert all(not v["clip"] for d in asked if d["triggerType"] != "keyEvent" for v in d["verdicts"].values())
    assert any(v["clip"] for d in asked for v in d["verdicts"].values())
    theme = "topic:00000000000000c4"
    assert all(theme not in d["candidates"] for d in decisions if d["eventSeq"] < THEME_FROM)
    assert any(theme in d["candidates"] for d in decisions)
    # A goal is pivotal for its team's follow: asked even inside the gap.
    riverton = {f"key:{k['id']}" for k in riverton_forgeham.key_rows() if k["contestantId"] == "riverton"}
    assert all("topic:00000000000000c1" in d["candidates"] for d in decisions if d["ref"] in riverton)


def test_follow_narratives_go_to_each_fired_topics_enabled_buckets_with_their_decision(runs):
    live, _ = runs
    fired = {(t, d["ref"]) for d in live["decisions"] for t in d["fired"]}
    topics = {t["topic_id"]: t for t in follow_topics()}
    assert live["follows"]
    for n in live["follows"]:
        assert n.kind == "subscription" and (n.topicId, n.trigger.ref) in fired
        assert n.userType in topics[n.topicId]["buckets"] and n.userType != "away:casual"
        assert n.id == f"sub:{MATCH}:{n.topicId}:{n.userType}:{n.seq}"
        wrap_up = n.trigger.type in ("halfTime", "fullTime")
        assert n.stepId == f"{MATCH}:sub:{n.topicId}:{n.trigger.ref}"
        assert n.decision["model"] == (None if wrap_up else "fake")
        assert n.decision.get("clip", False) is False or n.trigger.type == "keyEvent"
        assert n.promptVersion == "fake:subscription-author.v1"
    for pair in {(n.topicId, n.userType) for n in live["follows"]}:
        assert [n.seq for n in live["follows"] if (n.topicId, n.userType) == pair] == \
            list(range(1, 1 + sum((n.topicId, n.userType) == pair for n in live["follows"])))
    published = [n for n in live["sink"].published if n.kind == "subscription"]
    assert [n.id for n in published] == [n.id for n in live["follows"]]
    line = [n for n in live["follows"] if n.topicId == "topic:00000000000000c3"]
    assert line and all(n.storylineIds == [f"sl:{MATCH}:1"] for n in line)


def test_a_period_wrap_up_posts_once_per_topic_bucket_and_period_across_retries_and_restarts(runs):
    """The run fails and restarts mid-match (a fresh process from the stored checkpoint); the backlog run also
    replays everything. Each period end is queued once (closed periods), its decision is pinned by trigger ref and
    each narrative by step id, so a followed story never gets a second wrap-up for the same period."""
    crashed = run(crash="halfTime")  # the half-time wrap-up's publish fails; a fresh process resumes
    assert crashed["sink"].failed and len(crashed["asked"]) == 2
    assert [key(n) for n in crashed["follows"]] == [key(n) for n in runs[0]["follows"]]
    for r in (*runs, crashed):
        wraps = [(n.topicId, n.userType, n.trigger.ref) for n in r["follows"]
                 if n.trigger.type in ("halfTime", "fullTime")]
        assert wraps and len(wraps) == len(set(wraps))
        published = [(n.topicId, n.userType, n.trigger.ref) for n in r["sink"].published
                     if n.kind == "subscription" and n.trigger.type in ("halfTime", "fullTime")]
        assert set(published) == set(wraps)  # sent again only as the same narrative (at least once, same id)
        assert len({d["ref"] for d in r["decisions"] if d["triggerType"] in ("halfTime", "fullTime")}) == \
            len([d for d in r["decisions"] if d["triggerType"] in ("halfTime", "fullTime")])


def follow_clips(sink):
    return [c for c in sink.clips if c["type"] == "FollowClip"]


def clips_of(decisions):
    return sorted((t, d["ref"]) for d in decisions if d["triggerType"] == "keyEvent"
                  for t in d["fired"] if d["verdicts"][t]["clip"])


def test_each_clip_verdict_is_sent_once_as_its_own_follow_clip(runs):
    live, _ = runs
    clips = follow_clips(live["sink"])
    assert clips and len({c["id"] for c in clips}) == len(clips)
    assert sorted((c["topicId"], f"key:{c['eventId']}") for c in clips) == clips_of(live["decisions"])
    for c in clips:
        assert c["type"] == "FollowClip" and c["matchId"] == MATCH and c["decision"]["clip"]
        assert c["id"] == f"clip:{MATCH}:{c['topicId']}:{c['eventId']}"
        assert c["stepId"] == f"{MATCH}:sub:{c['topicId']}:key:{c['eventId']}"


def test_a_clip_reaches_the_backend_even_when_its_follow_narrative_is_dropped_as_ungrounded():
    # Every claim check finds an unsupported claim: no follow narrative survives, the clips still go out.
    unsupported = lambda key: 0.0 if key.endswith("_support") else 1.0  # every sentence claims, none is supported
    dropped = run(decide=lambda key, question, state: rule(key, question, state) if key.startswith("t")
                  else unsupported(key))
    assert not [n for n in dropped["follows"] if n.trigger.type == "keyEvent"]
    assert follow_clips(dropped["sink"])
    assert sorted((c["topicId"], f"key:{c['eventId']}") for c in follow_clips(dropped["sink"])) == \
        clips_of(dropped["decisions"])


def test_each_clipped_key_event_sends_one_moment_clip_for_the_shared_narratives(runs):
    """A key event of `clips.key_types` sends a `MomentClip` naming its step's buckets, apart from
    the narratives; none with `clips.shared` off."""
    live, backlog = runs
    clipped = {str(k["id"]) for k in riverton_forgeham.key_rows() if k["keyType"] in CONFIG["clips"]["key_types"]}
    moments = [c for c in live["sink"].clips if c["type"] == "MomentClip"]
    assert clipped and {str(c["eventId"]) for c in moments} == clipped
    for c in moments:
        assert c["id"] == f"mclip:{MATCH}:{c['eventId']}" and c["matchId"] == MATCH
        assert c["stepId"] == f"{MATCH}:key:{c['eventId']}" and c["buckets"] and c["eventSeq"] >= 0
    assert sorted(c["id"] for c in moments) == sorted(c["id"] for c in backlog["sink"].clips
                                                      if c["type"] == "MomentClip")
    off = run(config={**CONFIG, "clips": {**CONFIG["clips"], "shared": False}})
    assert not [c for c in off["sink"].clips if c["type"] == "MomentClip"]


def test_moment_clips_need_no_follow_nor_decision_model():
    """Shared clips read the served clip settings: no topics and no decision model still clip each key event."""
    data = EtlAsOf(riverton_forgeham.REPLAY, stats=riverton_forgeham.golden_stats(), actions_path=riverton_forgeham.ACTIONS,
                   keys=riverton_forgeham.key_rows(), trends=trends_at, spells=spells_at)
    store = MemoryStore()
    sink = MemorySink(store)
    engine = MatchOrchestrator(MATCH, data, FakeAgents(), store, sink, targets=StaticTargets(default_targets()[:3]),
                               follows=StaticTopics(), decisions=None)

    async def go():
        for body, seq in riverton_forgeham.timeline():
            data.limit = seq
            await engine.record(parse_notification(body))
            await engine.work()
    asyncio.run(go())
    clipped = {str(k["id"]) for k in riverton_forgeham.key_rows() if k["keyType"] in CONFIG["clips"]["key_types"]}
    assert {str(c["eventId"]) for c in sink.clips if c["type"] == "MomentClip"} == clipped
    assert not [c for c in sink.clips if c["type"] == "FollowClip"]


def test_a_backend_before_migration_041_serves_follows_with_both_clip_switches_off():
    old = targets_doc(1, [])
    del old["clips"]["always_for"], old["clips"]["shared"]
    source = HttpTopicSource(BASE, client(Backend({"/matches/demo/subscription-targets": old})))
    clips = asyncio.run(source.current("demo")).config["clips"]
    assert (clips["always_for"], clips["shared"]) == ([], False)


def test_a_clip_moment_is_asked_inside_the_gap_even_when_not_pivotal():
    config = {**CONFIG, "limits": {**CONFIG["limits"], "pivotal_key_types": []}}
    decisions = run(config=config)["decisions"]
    riverton = {f"key:{k['id']}" for k in riverton_forgeham.key_rows() if k["contestantId"] == "riverton"
               and k["keyType"] in CONFIG["clips"]["key_types"]}
    assert riverton and all("topic:00000000000000c1" in d["candidates"] for d in decisions if d["ref"] in riverton)


def test_the_decision_state_and_the_follow_author_get_the_authors_inputs(runs):
    live, _ = runs
    state = next(s for s, _ in live["calls"] if "The update being judged:" in s)
    for heading in ("game state statistics", "storylines", "match trends", "key event ledger", "match context",
                    "most recent insights"):
        assert heading in state
    store = live["store"]
    first = live["follows"][0]
    asked = [qs for s, qs in live["calls"] if s.startswith("This is the state")]
    assert asked and all("topic:" not in q.instructions for qs in asked for q in qs.values())
    authors = [v for a, v in run_with_calls() if a == "author" and "story_so_far" in v]
    assert authors and set(PLACEHOLDER.findall(shipped("subscription-author").template)) == \
        set(authors[0]) - {"bucket_id"}
    assert any(v["story_so_far"] != "Nothing yet." for v in authors)
    assert first.text.startswith(f"[{first.userType}] ")
    assert asyncio.run(store.subscription_narratives(MATCH, first.topicId, first.userType))[0].seq == 1


def test_a_goal_reaches_the_decision_with_the_score_before_and_after_it(runs):
    """The update carries the score it changed (from the ETL ledger), and a team follow is asked as everything
    about that team."""
    live, _ = runs
    updates = [s.split("The update being judged:\n", 1)[1].split("\n", 1)[0] for s, _ in live["calls"]
               if "The update being judged:" in s]
    goals = [u for u in updates if ": Goal for " in u or ": Own goal by " in u]
    assert goals and all(re.search(r"\. Score before: .+ \d+-\d+ .+; score now: .+ \d+-\d+ .+$", u) for u in goals)
    first = goals[0]
    assert first.split("Score before: ")[1].split(";")[0].count(" 0-0 ") == 1  # the opening goal starts from 0-0
    assert not any("Score before" in u for u in updates if u not in goals)  # only events that change the score
    team = [q for _, qs in live["calls"] for q in qs.values() if "Riverton Rovers." in q.instructions]
    assert team and all("everything about the team Riverton Rovers" in q.instructions for q in team)


def test_viewer_text_appears_only_in_its_own_topics_questions_never_in_the_shared_state(runs):
    live, _ = runs
    focus = {t["topic_id"]: t["spec"]["focus"] for t in follow_topics() if t["spec"]["focus"]}
    ids = [t["topic_id"] for t in follow_topics()]
    follows = [(state, asked) for state, asked in live["calls"] if state.startswith("This is the state")]
    assert follows and len(focus) == 2
    for state, asked in follows:
        assert not any(text in state for text in [*focus.values(), *ids])
        assert all(key.startswith("t") and "topic:" not in key for key in asked)  # positional keys, not topic ids
        for question in asked.values():
            assert sum(text in question.instructions for text in focus.values()) <= 1
    batched = [asked for _, asked in follows if sum(any(f in q.instructions for q in asked.values())
                                                     for f in focus.values()) == 2]
    assert batched  # both viewers' topics shared a request, each focus only in its own questions


_calls = {}


def run_with_calls():
    """The live run's agent calls (a separate small run up to half time, recorded once)."""
    if "calls" not in _calls:
        data = EtlAsOf(riverton_forgeham.REPLAY, stats=riverton_forgeham.golden_stats(),
                       actions_path=riverton_forgeham.ACTIONS, keys=riverton_forgeham.key_rows(), trends=trends_at,
                       spells=spells_at)
        agents, store = FakeAgents(), MemoryStore()
        engine = MatchOrchestrator(MATCH, data, agents, store, MemorySink(store),
                                   targets=StaticTargets(default_targets()[:3]), follows=StaticTopics(follow_topics()),
                                   decisions=FakeDecisions(rule=rule))

        async def go():
            for body, seq in riverton_forgeham.timeline()[:55]:
                data.limit = seq
                await engine.handle(parse_notification(body))
        asyncio.run(go())
        _calls["calls"] = agents.calls
    return _calls["calls"]


def test_a_restart_reuses_the_stored_decision_and_never_asks_again(runs):
    live, _ = runs
    crashed = run(crash=True)
    first, restarted = crashed["asked"]
    assert first.calls and restarted.calls
    follow = lambda model: {state for state, _ in model.calls if state.startswith("This is the state")}
    assert follow(first) and follow(restarted) and not follow(first) & follow(restarted)  # the decision was kept
    assert len(follow(first) | follow(restarted)) == sum(bool(d["candidates"]) and d["questions"] > 0
                                                         for d in live["decisions"])
    assert strip(crashed["decisions"]) == strip(live["decisions"])
    assert [key(n) for n in crashed["follows"]] == [key(n) for n in live["follows"]]
    sent = [n.id for n in crashed["sink"].published if n.kind == "subscription"]
    assert sorted(set(sent)) == sorted(n.id for n in live["follows"])  # the unsent one went on the retry


def test_a_new_follower_bucket_gets_the_story_so_far_once():
    joined = follow_topics()
    joined[0] = {**joined[0], "buckets": joined[0]["buckets"] + ["home:experienced"]}
    at = 40
    result = run(change=(at, joined))
    starts = [n for n in result["follows"] if n.trigger.type == "catchUp"]
    assert [(n.topicId, n.userType, n.seq) for n in starts] == [("topic:00000000000000c1", "home:experienced", 1)]
    assert starts[0].decision is None and starts[0].stepId.endswith(":catchUp:home:experienced")
    assert starts[0].trigger.reason == CONFIG["catch_up"]["reason"]  # the served tunable, not a code literal
    body = riverton_forgeham.timeline()[at - 1][0]
    assert (starts[0].matchTime.periodId, starts[0].matchTime.timeMin) <= (body["periodId"], body["timeMin"] + 1)


def test_a_story_so_far_dropped_as_ungrounded_is_tried_again_at_a_later_horizon():
    """The first catch-up's claim checks all fail (its excerpt is dropped); `catch_up.retries` queues it again
    when the next minute closes, at a later horizon, and that one is written."""
    reason, failed = CONFIG["catch_up"]["reason"], []

    def decide(key, question, state):
        if not key.startswith("t") and reason in state:
            if not failed or failed[0] == state:
                failed[:1] = [state]
                return 0.0 if key.endswith("_support") else 0.9  # claims, unsupported
            return 0.0
        return rule(key, question, state)
    joined = follow_topics()
    joined[0] = {**joined[0], "buckets": joined[0]["buckets"] + ["home:experienced"]}
    result = run(change=(40, joined), decide=decide)
    starts = [n for n in result["follows"] if n.trigger.type == "catchUp"]
    assert failed and [(n.topicId, n.userType) for n in starts] == [("topic:00000000000000c1", "home:experienced")]
    body = riverton_forgeham.timeline()[39][0]
    assert (starts[0].matchTime.periodId, starts[0].matchTime.timeMin) > (body["periodId"], body["timeMin"])


def test_graphql_pages_one_topics_narratives_for_one_bucket(runs):
    live, _ = runs
    n = live["follows"][0]
    query = """query ($m: String!, $t: String!, $u: String!, $after: Int, $first: Int) {
      subscriptionNarratives(matchId: $m, topicId: $t, userType: $u, afterSeq: $after, first: $first) {
        items { id seq topicId triggerType text decision { score confidence novelty model } }
        hasNextPage endCursor } }"""
    variables = {"m": MATCH, "t": n.topicId, "u": n.userType, "after": 0, "first": 1}
    page = asyncio.run(schema.execute(query, variables, context_value={"store": live["store"]}))
    assert page.errors is None
    data = page.data["subscriptionNarratives"]
    assert data["items"][0]["id"] == n.id and data["items"][0]["topicId"] == n.topicId
    assert data["items"][0]["decision"]["model"] == "fake" and data["endCursor"] == 1
    bad = asyncio.run(schema.execute(query, {**variables, "t": "nope"}, context_value={"store": live["store"]}))
    assert bad.errors


def test_a_purge_removes_the_follow_documents_and_a_restart_does_not_bring_them_back():
    data = EtlAsOf(riverton_forgeham.REPLAY, stats=riverton_forgeham.golden_stats(), actions_path=riverton_forgeham.ACTIONS,
                   keys=riverton_forgeham.key_rows(), trends=trends_at, spells=spells_at)
    store = MemoryStore()

    def router():
        return Router(data, FakeAgents(), store, MemorySink(store), targets=StaticTargets(default_targets()[:3]),
                      follows=StaticTopics(follow_topics()), decisions=FakeDecisions(rule=rule))
    timeline = riverton_forgeham.timeline()

    async def go():
        first = router()
        for body, _ in timeline[:40]:
            await first.handle(body)
            await first.idle()
        assert await store.decisions(MATCH) and await store.subscription_narratives(MATCH)
        result = await first.purge(MATCH)
        assert result["purged"]["subscriptionDecisions"] > 0 and result["purged"]["subscriptionNarratives"] > 0
        restarted = router()
        await restarted.start()
        for body, _ in timeline[40:50]:
            await restarted.handle(body)
        await restarted.idle()
        assert await store.decisions(MATCH) == [] and await store.subscription_narratives(MATCH) == []
    asyncio.run(go())


class FlakyDecisions(FakeDecisions):
    """Fails the first time it is asked each state (an outage), then answers as FakeDecisions."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.seen, self.failed = set(), 0

    async def decide(self, state, questions):
        if state not in self.seen:
            self.seen.add(state)
            self.failed += 1
            raise DecisionError("decision model unavailable")
        return await super().decide(state, questions)


def test_a_decision_outage_retries_the_checks_without_redoing_the_writing():
    def go(model):
        data = EtlAsOf(riverton_forgeham.REPLAY, stats=riverton_forgeham.golden_stats(),
                       actions_path=riverton_forgeham.ACTIONS, keys=riverton_forgeham.key_rows(), trends=trends_at,
                       spells=spells_at)
        agents, store = FakeAgents(), MemoryStore()
        engine = MatchOrchestrator(MATCH, data, agents, store, MemorySink(store),
                                   targets=StaticTargets(default_targets()[:3]), follows=StaticTopics(follow_topics()),
                                   decisions=model)

        async def run_all():
            for body, seq in riverton_forgeham.timeline()[:55]:
                data.limit = seq
                await engine.record(parse_notification(body))
                while True:
                    try:
                        await engine.work()
                        break
                    except DecisionError:
                        continue  # the worker's retry
        asyncio.run(run_all())
        return agents.calls, asyncio.run(store.narratives(MATCH, default_targets()[0]["bucket_id"]))
    steady, flaky = FakeDecisions(rule=rule), FlakyDecisions(rule=rule)
    calls, narratives = go(steady)
    flaky_calls, flaky_narratives = go(flaky)
    assert flaky.failed and flaky_calls == calls  # no writing-model call was repeated
    assert [n.text for n in flaky_narratives] == [n.text for n in narratives]
