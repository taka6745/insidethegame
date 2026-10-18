import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.domain import MatchEvent, RuleError
from backend.fakes import create_fake, normalise
from backend.fixtures import FixtureFeed


def test_var_correction_and_duplicate_are_counted_once():
    feed = FixtureFeed("synthetic-demo", 3)
    goal = MatchEvent(id="g1", match_id=feed.match_id, sequence=8, minute=33, team="away", type="goal")
    feed.accept_event(goal)
    assert not feed.accept_event(goal)
    assert feed.value("default", "goals", "away") == 1
    feed.accept_event(MatchEvent(id="var1", match_id=feed.match_id, sequence=9, minute=34,
                                team="away", type="goal_cancelled", related_event_id="g1"))
    assert feed.value("default", "goals", "away") == 0
    with pytest.raises(RuleError):
        feed.accept_event(goal.model_copy(update={"minute": 35}))


def test_fake_graphql_is_read_only_and_validates_match():
    with TestClient(create_fake("etl")) as client:
        body = client.post("/graphql", json={"query": '{ matchState(matchId:"synthetic-demo",team:"home") }'}).json()
        assert body["data"]["matchState"]["stats"]["shots"] == 1
        assert client.post("/graphql", json={"query": '{ matchEvents(matchId:"wrong") }'}).json()["errors"]
        assert client.post("/graphql", json={"query": 'mutation { deleteEverything }'}).json()["errors"]


def test_opta_style_timeline_matches_normalised_fixture():
    normal = json.loads(Path("fixtures/match.json").read_text())
    stream = [json.loads(line) for line in Path("fixtures/opta-style.jsonl").read_text().splitlines()]
    expected = [entry for entry in normal["timeline"] if entry["kind"] == "event"]
    actual = [entry for entry in stream if entry["kind"] == "event"]
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert normalise(a["payload"], normal["match_id"]) == MatchEvent(match_id=normal["match_id"], **e["payload"])


def test_narrative_fake_keeps_buckets_separate():
    with TestClient(create_fake("narrative")) as client:
        body = client.post("/graphql", json={"query": '{ context(matchId:"synthetic-demo",bucket:"away:casual") }'}).json()
        assert len(body["data"]["context"]["narratives"]) == 1
        assert body["data"]["context"]["narratives"][0]["team"] == "away"


def test_wrong_match_event_cannot_enter_fake_etl():
    with TestClient(create_fake("etl")) as client:
        item = json.loads(Path("fixtures/opta-style.jsonl").read_text().splitlines()[0])
        item["payload"]["matchId"] = "another-match"
        assert client.post("/events", json=item["payload"]).status_code == 422
        assert len(client.app.state.feed.events) == 7
