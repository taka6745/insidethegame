"""The storyline policy (every tunable of the analysis, storylines, repairs and claim checks) from the user
backend's `GET /storyline-policy`, with no fallback. `storyline-policy.json` is a byte copy of the backend seed
for tests and devtools only (`ShippedPolicy`)."""
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from narrative_engine.transport.http_cache import CachedJson

SHIPPED = Path(__file__).with_name("storyline-policy.json")
SECTIONS = {
    "analysis": ("max_observations", "max_evidence", "confidence_levels", "confidence_cap_short",
                 "confidence_cap_long", "short_windows", "value_tolerance", "relative_tolerance",
                 "small_counts_up_to", "label_chars", "headline_max_chars", "explanation_max_chars",
                 "outcome_max_chars"),
    "storylines": ("max_active", "dormant_after", "resolve_after", "quiet_fade", "beat_weight", "beats_counted",
                   "key_event_boost", "focus_repeat_penalty", "focus_recent_steps", "beats_shown",
                   "resolved_shown_minutes", "author_match_indicators", "reopen_within"),
    "repair": ("analyst_turns", "author_rewrites", "author_trim"),
    "claims": ("causal", "intent", "result", "comparison", "score"),
}
CLAIM = ("enabled", "claim", "support", "min_claim_probability", "min_support_probability", "repair", "analyst")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Policy:
    revision: int
    analysis: dict
    storylines: dict
    repair: dict
    claims: dict

    @classmethod
    def parse(cls, revision, value):
        """A policy from the served value; KeyError/TypeError if a section or key is missing."""
        missing = [f"{s}.{k}" for s, keys in SECTIONS.items() for k in keys if k not in value[s]]
        missing += [f"claims.{c}.{k}" for c in SECTIONS["claims"] for k in CLAIM if k not in value["claims"].get(c, {})]
        if missing:
            raise KeyError(f"storyline policy lacks {', '.join(missing)}")
        return cls(int(revision), *(dict(value[s]) for s in SECTIONS))


class PolicyUnavailable(RuntimeError):
    pass


class ShippedPolicy:
    """The seed copy, for tests and devtools only."""
    def __init__(self, value=None):
        self.policy = Policy.parse(0, value or json.loads(SHIPPED.read_text(encoding="utf-8")))

    async def current(self):
        return self.policy


class HttpPolicySource:
    def __init__(self, base_url, client, max_age=5.0):
        self.document = CachedJson(client, f"{base_url.rstrip('/')}/storyline-policy", max_age)
        self.reported = set()

    async def current(self):
        try:
            body = await self.document.get()
            policy = Policy.parse(body["revision"], body["value"])
        except Exception as error:  # unreachable or malformed
            problem = f"storyline policy unavailable from the user backend ({type(error).__name__})"
            if problem not in self.reported:  # log each problem once, not on every retry
                self.reported.add(problem)
                log.warning(problem)
            raise PolicyUnavailable(problem) from None
        self.reported.clear()
        return policy

    async def problems(self):
        try:
            await self.current()
        except PolicyUnavailable as error:
            return [str(error)]
        return [] if self.document.ok else ["user backend unreachable (using its last storyline policy)"]
