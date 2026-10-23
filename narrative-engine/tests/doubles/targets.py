"""Fixed audience targets for tests and devtools only: the original 12 buckets. The service always
reads the user backend's (audience.targets.HttpTargetSource) and never falls back to these."""
from narrative_engine.audience.targets import Targets


class StaticTargets:
    def __init__(self, items, revision=1):
        self.targets = Targets(revision, tuple(items))

    async def current(self, match_id):
        return self.targets


SUPPORT = {"home": "Supports the home team.", "away": "Supports the away team.", "neutral": "No team allegiance."}
LEVELS = {"simple": "Plain language, no jargon.", "casual": "The main storylines.",
          "experienced": "Tactical observations.", "analyst": "The statistics behind the story."}


def default_targets():
    """The original 12 buckets, for tests and devtools only (never the service)."""
    return [{"bucket_id": f"{s}:{level}", "selections": {"team": s, "fan_style": level}, "layers": [
        {"id": "team", "description": "Team support.",
         "option": {"id": s, "description": SUPPORT[s], "label": "{%s}" % s if s != "neutral" else "Neutral"}},
        {"id": "fan_style", "description": "Experience level.", "option": {"id": level, "description": LEVELS[level]}}]}
        for s in SUPPORT for level in LEVELS]


DEFAULT_BUCKETS = tuple(t["bucket_id"] for t in default_targets())
