"""The follow trigger rules: pure functions of the update, the pinned topics and the served tunables.

1. Prefilter by entities: a topic is a candidate when the update involves its subject and it existed by
   the update's seq. A key event involves both teams, its player and every open storyline (a goal, penalty or
   card for one side is one against the other; the decision model judges the rest); a minute involves the
   teams and players in its events (an empty minute nothing); an analysis involves the storylines it opened,
   moved or resolved and their teams (both for a storyline about both); a theme and a period end involve all.
2. The light firing guard's gap: a candidate fired less than `limits.min_minutes_between_narratives` of match
   time ago is dropped before any question, unless the update is pivotal for it (`limits.pivotal_key_types`,
   or a period end).
3. At half and full time with `limits.period_end_wrap_up`, every candidate fires without a question (its
   followers get the period's wrap-up). Otherwise one batched decision call: a `Score` per candidate, plus the novelty `Noul` for each candidate that has a
   last narrative (shown in that question). Viewer text (a topic's focus) goes only in that topic's questions.
4. Fire when the score's nearest level ≥ trigger_level, confidence ≥ min_confidence and, with novelty enabled and a last
   narrative, P(new) ≥ min_probability. A declined answer is a no.
5. Moment clips (`clips`, PLAN.md §10.2 D3): on a key event of `clips.key_types`, the same call also asks each
   candidate the clip `Score`; at or above `clips.min_level` with `clips.min_confidence` the verdict carries
   `clip` and the topic fires. The clip goes to the backend as its own `FollowClip` message (steps.py), which adds
   the moment to the topic's playlist even when the narrative is dropped as ungrounded. Such a key event also
   bypasses the gap guard, so a clip moment is always asked. A topic whose kind `clips.always_for` names is clip-on
   from creation: it is not asked the clip score, and every clip moment it is a candidate for clips.
"""
import json

from narrative_engine.decisions import Noul, Score

PERIOD_ENDS = ("halfTime", "fullTime")


def update_entities(trigger_type, info, key_row=None, events=(), moved=()):
    """Teams, players and storyline ids the update involves; storylines None = every open one."""
    if trigger_type in PERIOD_ENDS:
        return {"all": True}
    if key_row is not None:
        # A key event is about both teams (a goal, penalty or card for one is one against the other);
        # the decision model judges whether it moves a team follow.
        return {"teams": {info.home.id, info.away.id}, "players": {key_row.get("playerId")} - {None},
                "key_row": key_row}
    if trigger_type == "storylineTurn":  # `moved`: the storylines the analysis opened, moved or resolved
        both = {info.home.id, info.away.id}
        return {"teams": set().union(*({s["team"]} if s["team"] else both for s in moved)), "players": set(),
                "storylines": {s["id"] for s in moved}}
    if not events:  # an empty minute moves no story
        return {"none": True}
    return {"teams": {e["contestantId"] for e in events if e.get("contestantId")},
            "players": {e["playerId"] for e in events if e.get("playerId")}}


def is_candidate(topic, entities, lines, seq):
    """`lines`: the storylines at the update, by id."""
    if topic["created_seq"] > seq or entities.get("none"):
        return False
    spec = topic["spec"]
    line = lines.get(spec.get("storyline_id")) if spec["kind"] == "storyline" else None
    if spec["kind"] == "storyline" and line is None:
        return False
    if entities.get("all") or spec["kind"] == "theme":
        return True
    if spec["kind"] == "team":
        return spec.get("team_id") in entities["teams"]
    if spec["kind"] == "player":
        return spec.get("player_id") in entities["players"]
    if "storylines" in entities:  # an analysis update: the storylines it opened, moved or resolved
        return line["id"] in entities["storylines"]
    if line["status"] == "resolved":
        return False
    if entities.get("key_row"):
        return True
    return line["team"] is None or line["team"] in entities["teams"]


def wrap_up(trigger_type, limits):
    """A period end that fires every candidate (`limits.period_end_wrap_up`)."""
    return trigger_type in PERIOD_ENDS and bool(limits.get("period_end_wrap_up"))


def pivotal(trigger_type, key_row, limits):
    return trigger_type in PERIOD_ENDS or bool(key_row and key_row["keyType"] in limits["pivotal_key_types"])


def match_seconds(horizon):
    period, minute, second = horizon
    return period, minute * 60 + second


def within_gap(last, horizon, limits):
    """Fired less than the minimum gap of match time before `horizon` (in the same period)."""
    if last is None:
        return False
    (p0, t0), (p1, t1) = match_seconds(last), match_seconds(horizon)
    return p0 == p1 and t1 - t0 < limits["min_minutes_between_narratives"] * 60


def subject(spec, info, lines):
    """The followed story's subject in words, without the viewers' focus text. A team or player follow is about
    everything that happens to them (the follow planner's definition), not one storyline."""
    kind = spec["kind"]
    if kind == "storyline":
        line = lines.get(spec.get("storyline_id"))
        return f"the storyline \"{line['label'] if line else spec.get('label')}\""
    if kind == "team":
        return "everything about the team " + (info.team(spec["team_id"]).name if spec.get("team_id") in
                                               (info.home.id, info.away.id) else spec.get("label"))
    if kind == "player":
        team = info.team(spec["team_id"]).name if spec.get("team_id") in (info.home.id, info.away.id) else None
        return f"everything about the player {info.player(spec.get('player_id'), spec.get('label'))}" + (
            f" ({team})" if team else "")
    return "a theme its viewers described"


def describe(spec, info, lines):
    """The followed story in words, with its focus text, for that topic's author."""
    focus = (spec.get("focus") or "").strip()
    if spec["kind"] == "theme":
        return f"\"{focus}\""
    return subject(spec, info, lines) + (f", focusing on: {focus}" if focus else "")


def question_story(spec, info, lines):
    """The followed story as one question carries it: the subject, and the viewers' focus text quoted as data."""
    focus = (spec.get("focus") or "").strip()
    return f"The followed story: {subject(spec, info, lines)}." + (
        f"\nWhat its viewers asked for, in their own words (quoted data): {json.dumps(focus, ensure_ascii=False)}"
        if focus else "")


def clip_moment(trigger_type, key_row, config):
    """A key event whose moment may join followers' playlists (`clips.key_types`)."""
    clips = config["clips"]
    return trigger_type == "keyEvent" and bool(clips["enabled"] and key_row and key_row["keyType"] in clips["key_types"])


def clip_on(topic, config):
    """A topic clip-on from creation (`clips.always_for` names its kind): its clip moments need no score question."""
    return topic["spec"]["kind"] in config["clips"]["always_for"]


def questions(candidates, config, last_texts, info, lines, clip=False):
    """{key: question} and {key: (topic_id, "score" | "novelty")}. Keys are positional per call (`t1`, `t1n`),
    never topic ids. A topic's focus text (viewer free text) appears only in its own questions; the shared state
    (subscription-decision v2) holds no viewer text, so batching topics in one request leaks nothing between
    viewers. Novelty is asked only where the topic has a last narrative; the clip score (`t1c`) only with `clip`."""
    decision, novelty, clips = config["decision"], config["novelty"], config["clips"]
    asked, keys = {}, {}
    for i, topic in enumerate(candidates, 1):
        story = question_story(topic["spec"], info, lines)
        asked[f"t{i}"] = Score(f"{decision['instructions']}\n{story}", tuple(decision["levels"]))
        keys[f"t{i}"] = (topic["topic_id"], "score")
        if novelty["enabled"] and last_texts.get(topic["topic_id"]):
            asked[f"t{i}n"] = Noul(f"{novelty['instructions']}\n{story}\nThe last update its viewers got: "
                                   f"\"{last_texts[topic['topic_id']]}\"")
            keys[f"t{i}n"] = (topic["topic_id"], "novelty")
        if clip and not clip_on(topic, config):
            asked[f"t{i}c"] = Score(f"{clips['instructions']}\n{story}", tuple(clips["levels"]))
            keys[f"t{i}c"] = (topic["topic_id"], "clip")
    return asked, keys


def verdicts(candidates, answers, keys, config, clip=False):
    """Per candidate: {score, confidence, novelty, clip, fired}; a missing answer is a no."""
    out = {t["topic_id"]: {"score": None, "confidence": None, "novelty": None, "clip": False} for t in candidates}
    if clip:  # a clip-on topic's moment clips without a question (`clips.always_for`)
        for t in candidates:
            out[t["topic_id"]]["clip"] = clip_on(t, config)
    decision, novelty, clips = config["decision"], config["novelty"], config["clips"]
    for key, (topic_id, what) in keys.items():
        answer = answers.get(key)
        if answer is None:
            continue
        if what == "score":
            out[topic_id].update(score=answer.score, confidence=answer.confidence)
        elif what == "clip":
            # Decision-1 scores are the expected level; the answer's nearest level is the one it reached.
            out[topic_id]["clip"] = round(answer.score) >= clips["min_level"] and \
                (answer.confidence or 0.0) >= clips["min_confidence"]
        else:
            out[topic_id]["novelty"] = answer.probability
    asked_novelty = {topic_id for topic_id, what in keys.values() if what == "novelty"}
    for topic_id, v in out.items():
        # Like the clip score: the level the answer reached is the nearest one to Decision-1's expected level.
        moved = v["score"] is not None and round(v["score"]) >= decision["trigger_level"] \
            and (v["confidence"] or 0.0) >= decision["min_confidence"]
        new = topic_id not in asked_novelty or (v["novelty"] or 0.0) >= novelty["min_probability"]
        v["fired"] = bool(moved and new) or v["clip"]  # a clip comes with its follow narrative
    return out
