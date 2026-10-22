"""The versioned SPADL data dictionary (feed_profiles/spadl-v1.json), checked against the action model."""
import hashlib
import json
from functools import cache
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ConfigDict, Field

from backend.models.actions import ActionType, Bodypart, PASS_FAMILY, Result, SHOT_FAMILY, SpadlAction, Zone

PROFILE = Path(__file__).parent / 'feed_profiles' / 'spadl-v1.json'


class FeedReference(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    contract_id: str = Field(min_length=1)
    provenance: str
    fields: dict[str, str]
    derived: dict[str, str]
    events: dict[str, str]
    results: dict[str, str]
    bodyparts: dict[str, str]
    zones: dict[str, str]
    families: dict[str, str]
    outside_spadl: list[str]
    guarantees: list[str]
    unavailable: list[str]

    @classmethod
    def load(cls, path: Path = PROFILE):
        return cls.model_validate_json(path.read_text())

    def describe(self, model=SpadlAction) -> dict:
        """The dictionary agents read; every key set must equal the model's fields and enums."""
        schema = model.model_json_schema()
        checks = {'fields': set(schema['properties']), 'events': set(get_args(ActionType)),
                  'results': set(get_args(Result)), 'bodyparts': set(get_args(Bodypart)), 'zones': set(get_args(Zone))}
        for name, expected in checks.items():
            if set(getattr(self, name)) != expected:
                raise ValueError(f'SPADL profile {name} differ from the action model; review the profile')
        for family, members in (('passes', PASS_FAMILY), ('shots', SHOT_FAMILY)):
            if not all(kind in self.families[family] for kind in members):
                raise ValueError(f'SPADL profile family {family} differs from the contract')
        return {'contract_id': self.contract_id,
                'schema_sha256': hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
                **self.model_dump(exclude={'contract_id'})}


@cache
def spadl_reference() -> str:
    return json.dumps(FeedReference.load().describe())


def reference() -> dict:
    """A fresh copy: callers adapt it per match."""
    return json.loads(spadl_reference())
