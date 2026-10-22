"""The narrative engine's messages (narrative-engine/contracts/README.md, Output 2): narratives and follow clips."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EngineTrigger(BaseModel):
    model_config = ConfigDict(extra='ignore')
    type: str = Field(max_length=40)
    ref: str = Field(max_length=200)
    reason: str = Field(max_length=2000)
    eventIds: list[int | str] = Field(default_factory=list, max_length=20)


class EngineMatchTime(BaseModel):
    model_config = ConfigDict(extra='ignore')
    periodId: int = Field(ge=1, le=5)
    timeMin: int = Field(ge=0, le=200)


class EngineNarrative(BaseModel):
    """Extra fields are ignored so the engine can add metadata without breaking delivery."""
    model_config = ConfigDict(extra='ignore')
    id: str = Field(min_length=1, max_length=300)
    matchId: str = Field(min_length=1, max_length=200)
    userType: str = Field(pattern=r'^[a-z0-9][a-z0-9_:-]{0,99}$')
    seq: int = Field(ge=1)
    stepId: str = Field(max_length=300)
    trigger: EngineTrigger
    matchTime: EngineMatchTime
    text: str = Field(min_length=1, max_length=3000)
    promptVersion: str | None = Field(default=None, max_length=200)
    tokens: dict | None = None
    createdAt: str = Field(max_length=60)
    timeSec: int | None = Field(default=None, ge=0, le=59)
    audienceRevision: int | None = None
    # The canonical seq (ETL watermark) the narrative was written from; shown only once a viewer's snapshot reaches it.
    eventSeq: int | None = Field(default=None, ge=0)
    # `subscription`: a followed story's narrative for one topic and bucket (contracts §8b), else a bucket insight.
    kind: Literal['bucket', 'subscription'] = 'bucket'
    topicId: str | None = Field(default=None, pattern=r'^topic:[0-9a-f]{16}$')
    decision: dict | None = None  # the trigger decision (score, confidence, model); stored as delivered
    storylineIds: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def topic_for_subscriptions(self):
        if (self.kind == 'subscription') != (self.topicId is not None):
            raise ValueError('a subscription narrative needs topicId; a bucket narrative has none')
        return self

    @property
    def clock_seconds(self):
        """Broadcast clock of the data the narrative is about. timeSec 59 (scheduled, period-end and
        minute catch-up steps) or unknown covers the whole minute, so it shows at the next minute's :00;
        a key event's second is kept."""
        second = 59 if self.timeSec is None else self.timeSec
        return self.matchTime.timeMin * 60 + (60 if second == 59 else second)


class EngineFollowClip(BaseModel):
    """A followed topic's moment clip (contracts Output 2, `FollowClip`): Decision-1 judged the key event worth a
    clip for the topic. Sent apart from the topic's narratives, so it does not depend on their grounding."""
    model_config = ConfigDict(extra='ignore')
    type: Literal['FollowClip']
    id: str = Field(min_length=1, max_length=300)
    matchId: str = Field(min_length=1, max_length=200)
    topicId: str = Field(pattern=r'^topic:[0-9a-f]{16}$')
    # The key event's MA3 id (ETL keyEvents.id = rawEvents.id): the clip's key moment is `km:{eventId}`.
    eventId: int | str
    # The canonical seq the decision was made at; the clip shows once a viewer's snapshot reaches it.
    eventSeq: int = Field(ge=0)
    stepId: str = Field(min_length=1, max_length=300)
    decision: dict | None = None


class EngineMomentClip(BaseModel):
    """A key event's clip on the shared bucket narratives (contracts Output 2, `MomentClip`; PLAN.md §10.2 D7): the
    engine sends it for a key event of `subscriptions.clips.key_types` with `clips.shared` on, apart from the
    narratives, so their grounding never decides whether the clip shows."""
    model_config = ConfigDict(extra='ignore')
    type: Literal['MomentClip']
    id: str = Field(min_length=1, max_length=300)
    matchId: str = Field(min_length=1, max_length=200)
    buckets: list[str] = Field(min_length=1, max_length=50)
    eventId: int | str  # the clip's key moment is `km:{eventId}`
    eventSeq: int = Field(ge=0)
    stepId: str = Field(min_length=1, max_length=300)
