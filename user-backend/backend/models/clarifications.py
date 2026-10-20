"""A single bounded follow-up question, with optional choices and free text."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FollowUpQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=500)
    options: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=5)
    allow_free_text: bool = True

    @model_validator(mode='after')
    def meaningful(self):
        self.question = self.question.strip()
        self.options = list(dict.fromkeys(option.strip() for option in self.options))
        if not self.question or any(not option for option in self.options):
            raise ValueError('Clarification text cannot be blank')
        if not self.options and not self.allow_free_text:
            raise ValueError('A clarification must allow an answer')
        return self
