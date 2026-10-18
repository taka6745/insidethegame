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

    def match_events(self):
        """Historical event tool for agent investigations or genuinely custom calculations."""
        return self.query(self.etl_url, "query($id: ID!){matchEvents(matchId:$id)}",
                          {"id": self.match_id})["matchEvents"]

    def view(self, bucket, team, calculation_ids=()):
        match = self.query(self.etl_url, "query($id: ID!, $team: String!){matchState(matchId:$id,team:$team)}",
                           {"id": self.match_id, "team": team})["matchState"]
        narrative = self.query(self.narrative_url,
            "query($id: ID!, $bucket: String!){context(matchId:$id,bucket:$bucket)}",
            {"id": self.match_id, "bucket": bucket})["context"]
        custom = {}
        if calculation_ids:
            # Only custom fixture pins need raw history. Standard stats are authoritative ETL values.
            # Incremental custom history/live handoff is still to build.
            local = FixtureFeed(self.match_id, self.slots)
            local.events.clear()
            for event in self.match_events():
                local.accept_event(MatchEvent(**event))
            custom = {key: local.value("custom", key, team) for key in calculation_ids}
        return {"defaults": narrative["stat_ids"], "narratives": narrative["narratives"],
                "key_moments": match["key_moments"],
                "values": {"default": match["stats"], "custom": custom}}
