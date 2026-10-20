"""Read-only data knowledge attached to a goal request, with no extra model call."""
import hashlib
import json
from pathlib import Path


class EventDataSkill:
    def __init__(self, feed_reference: dict):
        document = (Path(__file__).parent / "skills/event-data/SKILL.md").read_text()
        # Frontmatter is discovery metadata, not model instructions.
        self._payload = {"instructions": document.split("---", 2)[2].strip(),
                         "feed_reference": json.loads(json.dumps(feed_reference))}
        self.fingerprint = hashlib.sha256(json.dumps(self._payload, sort_keys=True).encode()).hexdigest()

    def context(self, feed_reference: dict | None = None) -> dict:
        # A request cannot mutate the reference used by another viewer.
        payload = json.loads(json.dumps(self._payload))
        if feed_reference is not None:
            payload['feed_reference'] = json.loads(json.dumps(feed_reference))
        return payload
