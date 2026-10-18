"""Read-only adapters to the local fake GraphQL services. No narrative generation calls."""
import httpx

from .domain import MatchEvent, RuleError
from .fixtures import FixtureFeed


class FixtureServices(FixtureFeed):
    def __init__(self, match_id, slots, etl_url, narrative_url):
        super().__init__(match_id, slots)
        self.etl_url, self.narrative_url = etl_url, narrative_url

    @staticmethod
    def query(url, query, variables):
        try:
            response = httpx.post(url, json={"query": query, "variables": variables}, timeout=5)
            response.raise_for_status()
            body = response.json()
            if body.get("errors"):
                raise ValueError("Upstream GraphQL returned errors")
            return body["data"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise RuleError("upstream_unavailable", "The fixture service is unavailable; retry shortly", 503) from exc

    def accept_event(self, event):
        # Runtime fixtures are authoritative in fake ETL; this endpoint only wakes viewers.
        if event.match_id != self.match_id:
            raise RuleError("wrong_match", "Only the configured match is supported", 422)
        return True

    def view(self, bucket, team):
        match = self.query(self.etl_url, "query($id: ID!, $team: String!){matchState(matchId:$id,team:$team)}",
                           {"id": self.match_id, "team": team})["matchState"]
        narrative = self.query(self.narrative_url,
            "query($id: ID!, $bucket: String!){context(matchId:$id,bucket:$bucket)}",
            {"id": self.match_id, "bucket": bucket})["context"]
        # Harness backfill on each snapshot. Real incremental history/live handoff is still to build.
        local = FixtureFeed(self.match_id, self.slots)
        local.events.clear()
        for event in match["events"]:
            local.accept_event(MatchEvent(**event))
        view = local.view(bucket, team)
        view["defaults"], view["narratives"] = narrative["stat_ids"], narrative["narratives"]
        view["values"]["default"], view["key_moments"] = match["stats"], match["key_moments"]
        return view
