"""Which buckets to write for, and how to describe each one to the author.

The user backend owns audience definitions (AGENTS.md). Its read-only
`GET /matches/{matchId}/audience-config` lists `generation_targets`: the buckets enabled in its
configuration (toggled in /dev/; there is no viewer presence), each with its layer and option
descriptions. The engine writes only for those; an empty list means write nothing.
The engine asks by its run-scoped matchId; the backend resolves the fixture's audience template.
There is no fallback: with no answer from the backend, authoring waits.
Fixed buckets for tests and devtools live in `devtools/targets.py`; the service never uses them.
"""
from dataclasses import dataclass
from typing import Protocol

from narrative_engine.transport.http_cache import CachedJson


@dataclass(frozen=True)
class Targets:
    revision: int
    items: tuple  # generation_targets dicts: bucket_id, selections, layers[{id, description, option{id, description, label?, team?}}]

    @property
    def by_bucket(self):
        return {t["bucket_id"]: t for t in self.items}


class TargetSource(Protocol):
    async def current(self, match_id) -> Targets: ...


class HttpTargetSource:
    def __init__(self, base_url, client, max_age=5.0):
        self.base_url, self.client, self.max_age = base_url.rstrip("/"), client, max_age
        self.documents = {}

    async def current(self, match_id):
        if match_id not in self.documents:
            self.documents[match_id] = CachedJson(
                self.client, f"{self.base_url}/matches/{match_id}/audience-config", self.max_age)
        body = await self.documents[match_id].get()
        return Targets(int(body["revision"]), tuple(body["generation_targets"]))

    def forget(self, match_id):
        self.documents.pop(match_id, None)


def supported_side(target):
    """`home`/`away` if any option backs a team: its `team` field, else a label naming only `{home}` or `{away}`."""
    for layer in target["layers"]:
        option = layer["option"]
        if option.get("team") in ("home", "away"):
            return option["team"]
        sides = [s for s in ("home", "away") if "{%s}" % s in (option.get("label") or "")]
        if len(sides) == 1:
            return sides[0]
    return None


def framing(target, info):
    """The author's audience text: every layer's meaning and this bucket's option, plus the teams."""
    lines = [f"Audience bucket {target['bucket_id']}:"]
    lines += [f"- {layer['description']} {layer['option']['description']}" for layer in target["layers"]]
    lines.append(f"Home team: {info.home.name}. Away team: {info.away.name}.")
    team = {"home": info.home, "away": info.away}.get(supported_side(target))
    if team:
        lines.append(f"This audience supports {team.name}.")
    return "\n".join(lines)

