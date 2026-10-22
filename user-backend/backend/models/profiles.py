"""Demo accounts edited under /dev/profiles. `selections` maps default-template layer ids to option ids."""
from typing import Annotated

from pydantic import Field, model_validator

from .audiences import Key, StrictModel


class DemoProfile(StrictModel):
    id: Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9-]{0,63}$')]
    display_name: Annotated[str, Field(min_length=1, max_length=80)]
    # Account defaults: the viewer starts on the enabled bucket that matches most of these.
    selections: Annotated[dict[Key, Key], Field(max_length=8)]


class DemoProfiles(StrictModel):
    profiles: list[DemoProfile] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def unique(self):
        if len({p.id for p in self.profiles}) != len(self.profiles):
            raise ValueError('Profile ids must be unique')
        return self
