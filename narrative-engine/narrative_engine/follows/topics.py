"""Followed topics and the follow tunables, from the user backend's `GET /matches/{matchId}/subscription-targets`
(ETag; contracts/README.md#subscription-targets). The backend owns follows; the engine only reads them.
Fixed topics for tests: tests/doubles/follows.py.
"""
from dataclasses import dataclass
from typing import Protocol

from narrative_engine.transport.http_cache import CachedJson

CONFIG = ("decision", "novelty", "prefilter", "limits", "catch_up", "clips")


@dataclass(frozen=True)
class FollowTargets:
    revision: int
    config_revision: int
    config: dict   # decision, novelty, prefilter, limits, catch_up, clips as served
    topics: tuple  # {topic_id, created_seq, followers, buckets, spec}

    @classmethod
    def parse(cls, body):
        """KeyError/TypeError/ValueError when the document lacks a field the pipeline reads."""
        config = {k: dict(body[k]) for k in CONFIG}
        for key in ("instructions", "levels", "trigger_level", "min_confidence"):
            config["decision"][key]
        for key in ("enabled", "instructions", "min_probability"):
            config["novelty"][key]
        config["limits"]["min_minutes_between_narratives"], config["limits"]["pivotal_key_types"]
        config["limits"]["period_end_wrap_up"]
        config["catch_up"]["reason"], int(config["catch_up"]["retries"])
        config["clips"] = dict(config["clips"])
        for key in ("enabled", "key_types", "instructions", "levels", "min_level", "min_confidence"):
            config["clips"][key]
        # A backend not yet migrated serves neither (both off), so the engine may
        # deploy first without stopping follows.
        config["clips"]["always_for"] = list(config["clips"].get("always_for", ()))
        config["clips"]["shared"] = bool(config["clips"].get("shared", False))
        topics = tuple({"topic_id": t["topic_id"], "created_seq": int(t["created_seq"]), "buckets": list(t["buckets"]),
                        "spec": dict(t["spec"])} for t in body["topics"])
        return cls(int(body["revision"]), int(body["config_revision"]), config, topics)


class TopicSource(Protocol):
    async def current(self, match_id) -> FollowTargets: ...


class HttpTopicSource:
    def __init__(self, base_url, client, max_age=5.0):
        self.base_url, self.client, self.max_age = base_url.rstrip("/"), client, max_age
        self.documents = {}

    async def current(self, match_id):
        if match_id not in self.documents:
            self.documents[match_id] = CachedJson(
                self.client, f"{self.base_url}/matches/{match_id}/subscription-targets", self.max_age)
        return FollowTargets.parse(await self.documents[match_id].get())

    def forget(self, match_id):
        self.documents.pop(match_id, None)
