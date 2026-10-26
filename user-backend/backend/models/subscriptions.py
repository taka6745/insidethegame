"""Story follows (local/README.md Contracts §8b): a viewer follows one story per match; identical follows share a topic."""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.models.events import MAX_MATCH_EVENTS
from backend.models.questions import Strict

Kind = Literal['storyline', 'team', 'player', 'theme']
Id = Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_:.-]{0,99}$')]


class FollowSpec(Strict):
    """What a follow is about. `storyline`: one engine storyline; `team`/`player`: everything about them;
    `theme`: the viewer's own words (`focus`). `focus` narrows any kind; `label` is shown to the viewer."""
    kind: Kind
    storyline_id: Id | None = None
    team_id: Id | None = None
    player_id: Id | None = None
    focus: str = Field(default='', max_length=300)
    label: str = Field(min_length=1, max_length=80)

    @model_validator(mode='after')
    def subject(self):
        needed = {'storyline': self.storyline_id, 'team': self.team_id, 'player': self.player_id,
                  'theme': self.focus.strip()}[self.kind]
        if not needed:
            raise ValueError(f'a {self.kind} follow needs its ' + {'theme': 'focus'}.get(self.kind, f'{self.kind}_id'))
        return self

    def topic_id(self, match_id):
        """Identical follows (same subject and focus) share one generation topic; the label is not part of it."""
        key = [match_id, self.kind, self.storyline_id, self.team_id, self.player_id, ' '.join(self.focus.lower().split())]
        return 'topic:' + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]


class FollowRequest(Strict):
    spec: FollowSpec
    seq: int | None = Field(default=None, ge=0, le=MAX_MATCH_EVENTS)  # the snapshot the viewer sees
    # Another live match whose story this is (a cross-match option's `match_id`); its own position
    # bounds it, not `seq`.
    match_id: Id | None = None


class PlannerDraft(Strict):
    """The subscription planner's structured reply; entity names are resolved by code, never trusted as ids."""
    action: Literal['follow', 'clarify', 'unfollow', 'none']
    kind: Kind | None = None
    subject: str | None = Field(default=None, max_length=120)  # the storyline, team or player as the viewer named it
    focus: str = Field(default='', max_length=300)
    label: str | None = Field(default=None, max_length=80)
    reply: str = Field(min_length=1, max_length=600)
    # For "clarify": the follows the viewer could choose between, each resolved by code like the main subject.
    options: list['PlannerOption'] = Field(default_factory=list, max_length=4)


class PlannerOption(Strict):
    kind: Kind
    subject: str | None = Field(default=None, max_length=120)
    focus: str = Field(default='', max_length=300)
    label: str = Field(min_length=1, max_length=80)


PlannerDraft.model_rebuild()
_OPTION = {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'subject', 'focus', 'label'],
           'properties': {'kind': {'type': 'string', 'enum': ['storyline', 'team', 'player', 'theme']},
                          'subject': {'type': ['string', 'null']}, 'focus': {'type': 'string'},
                          'label': {'type': 'string'}}}

PLANNER_SCHEMA = {'type': 'json_schema', 'json_schema': {'name': 'follow_plan', 'strict': True, 'schema': {
    'type': 'object', 'additionalProperties': False,
    'required': ['action', 'kind', 'subject', 'focus', 'label', 'reply', 'options'],
    'properties': {'action': {'type': 'string', 'enum': ['follow', 'clarify', 'unfollow', 'none']},
                   'kind': {'type': ['string', 'null'], 'enum': ['storyline', 'team', 'player', 'theme', None]},
                   'subject': {'type': ['string', 'null']}, 'focus': {'type': 'string'},
                   'label': {'type': ['string', 'null']}, 'reply': {'type': 'string'},
                   'options': {'type': 'array', 'maxItems': 4, 'items': _OPTION}}}}}
