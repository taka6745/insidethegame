"""Narrative prompt templates: `{name}` placeholders, fixed per role by the seed."""
import re
from typing import Literal

from pydantic import Field

from .audiences import StrictModel

# The engine's roles, plus subscription-planner (this service's follow chat).
Role = Literal['minute-summary', 'context-compression', 'match-analyst', 'narrative-author', 'subscription-planner',
               'subscription-decision', 'subscription-author']
ROLES: tuple[Role, ...] = ('minute-summary', 'context-compression', 'match-analyst', 'narrative-author',
                           'subscription-planner', 'subscription-decision', 'subscription-author')
MAX_TEMPLATE = 20_000
PLACEHOLDER = re.compile(r'\{([a-z_]+)\}')


def placeholders(template):
    return sorted(set(PLACEHOLDER.findall(template)))


class SavePrompt(StrictModel):
    template: str = Field(min_length=1, max_length=MAX_TEMPLATE)
    expected_version: int = Field(ge=1, le=2147483646)
