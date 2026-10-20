from backend.fixtures import FixtureFeed
from backend.upstream import FixtureServices


def upstream(monkeypatch):
    feed = FixtureServices("synthetic-demo", 3, "http://etl/graphql", "http://narrative/graphql")
    calls = []
    stats = {"goals": 7, "cards": 8, "shots": 23, "possession": 61}

    def query(url, document, variables):
        calls.append(document)
        if "matchState(" in document:
            return {"matchState": {"stats": stats, "key_moments": []}}
        if "context(" in document:
            return {"context": {"stat_ids": ["goals", "shots", "cards"], "narratives": []}}
        assert "matchEvents(" in document
        return {"matchEvents": [{"id": "head-1", "match_id": "synthetic-demo", "sequence": 1,
                                 "minute": 25, "type": "pass", "body_part": "head", "team": "home"}]}

    monkeypatch.setattr(feed, "query", query)
    # Fail if any runtime path tries to reconstruct a standard stat from raw events.
    original = FixtureFeed.value

    def custom_only(self, kind, key, team):
        assert kind == "custom", "Standard statistics must come directly from ETL GraphQL"
        return original(self, kind, key, team)

    monkeypatch.setattr(FixtureFeed, "value", custom_only)
    return feed, calls, stats


def test_standard_cards_use_etl_values_without_fetching_events(monkeypatch):
    feed, calls, stats = upstream(monkeypatch)
    view = feed.view("home:analytical", "home")
    assert view["values"] == {"default": stats, "custom": {}}
    assert len(calls) == 2 and not any("matchEvents(" in call for call in calls)


def test_custom_pin_queries_history_without_recalculating_standard_stats(monkeypatch):
    feed, calls, stats = upstream(monkeypatch)
    view = feed.view("home:analytical", "home", ["fixture-headers"])
    assert view["values"] == {"default": stats, "custom": {"fixture-headers": 1}}
    assert sum("matchEvents(" in call for call in calls) == 1


def test_historical_investigation_uses_separate_graphql_query(monkeypatch):
    feed, calls, _ = upstream(monkeypatch)
    assert feed.match_events()[0]["id"] == "head-1"
    assert len(calls) == 1 and "matchEvents(" in calls[0]
