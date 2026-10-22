"""Match clock, audience buckets and the ETL notification messages.

The clock follows the ETL's Opta convention (see etl/contracts/README.md): `timeMin` is
0-based, first-half added time keeps counting (46 = 45+2') and the second half restarts
at 45, so a minute is only unique together with its period.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

PERIOD_START = {1: 0, 2: 45, 3: 90, 4: 105}
PERIOD_END = {1: 45, 2: 90, 3: 105, 4: 120}


@dataclass(frozen=True, order=True)
class MatchClock:
    periodId: int
    timeMin: int

    @property
    def label(self):
        """Broadcast style, as the matchStatsAsOf view writes minuteLabel."""
        end = PERIOD_END.get(self.periodId, 120)
        shown = self.timeMin + 1
        return f"{end}+{shown - end}'" if shown > end else f"{shown}'"

    @property
    def key(self):
        return f"{self.periodId}-{self.timeMin:03d}"

    def next(self):
        return MatchClock(self.periodId, self.timeMin + 1)

    @classmethod
    def parse(cls, key):
        period, minute = key.split("-")
        return cls(int(period), int(minute))


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class MinuteClosed:
    matchId: str
    clock: MatchClock
    windowEnd: datetime


@dataclass(frozen=True)
class KeyEventDetected:
    matchId: str
    id: int
    keyType: str
    detail: Optional[str]
    contestantId: str
    playerId: Optional[str]
    clock: MatchClock
    timeSec: int
    eventTime: datetime
    relatedEventId: Optional[int]


@dataclass(frozen=True)
class PeriodChanged:
    matchId: str
    periodId: int
    started: bool
    eventTime: datetime
    clock: Optional[MatchClock] = None  # the Start/End event's minute and second, when the body has them
    timeSec: Optional[int] = None


HANDLED = ("MinuteClosed", "KeyEventDetected", "PeriodStarted", "PeriodEnded")


def parse_notification(body, message_type=None):
    """Turn a Service Bus body (plus its `messageType` user property) into a message.

    Local replays carry `messageType` in the body; Service Bus carries it as a user
    property. Returns None for types the engine does not handle, before reading any field.
    """
    kind = message_type or body.get("messageType")
    if kind not in HANDLED:
        return None
    match_id = body["matchId"]
    if kind == "MinuteClosed":
        return MinuteClosed(match_id, MatchClock(int(body["periodId"]), int(body["timeMin"])),
                            parse_time(body["windowEnd"]))
    if kind == "KeyEventDetected":
        related = body.get("relatedEventId")
        return KeyEventDetected(
            match_id, int(body["id"]), body["keyType"], body.get("detail"), body["contestantId"],
            body.get("playerId"), MatchClock(int(body["periodId"]), int(body["timeMin"])), int(body["timeSec"]),
            parse_time(body["eventTime"]), int(related) if related not in (None, "") else None,
        )
    period, minute, second = int(body["periodId"]), body.get("timeMin"), body.get("timeSec")
    timed = minute is not None and second is not None
    return PeriodChanged(match_id, period, kind == "PeriodStarted", parse_time(body["eventTime"]),
                         MatchClock(period, int(minute)) if timed else None, int(second) if timed else None)


def minutes_between(last, target, period_end):
    """Minutes after `last` up to and including `target`, crossing period ends.

    `period_end(periodId)` returns the period's final MatchClock, or None if not known yet;
    returns None when an unknown period end blocks the walk.
    """
    current = MatchClock(1, PERIOD_START[1]) if last is None else last.next()
    clocks = []
    while current <= target:
        if current.periodId < target.periodId:
            end = period_end(current.periodId)
            if end is None:
                return None
            if current > end:
                current = MatchClock(current.periodId + 1, PERIOD_START[current.periodId + 1])
                continue
        clocks.append(current)
        current = current.next()
    return clocks


@dataclass(frozen=True)
class Trigger:
    """Why a narrative step runs. `ref` makes the step ID deterministic for idempotency."""
    type: str  # keyEvent, scheduled, halfTime, fullTime, catchUp, storylineTurn (analysis, subscriptionEval/Start: steps)
    ref: str
    reason: str
    eventIds: tuple = ()


@dataclass(frozen=True)
class AgentResult:
    text: str
    model: Optional[str] = None
    promptVersion: Optional[str] = None
    tokens: Optional[dict] = None


def merge_usage(usages):
    """Token counts summed over several calls (None when none were reported)."""
    usages = [u for u in usages if u]
    if not usages:
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {k: sum(u.get(k) or 0 for u in usages) for k in keys}


@dataclass
class ContextBlock:
    id: str
    matchId: str
    level: int
    coversFrom: MatchClock
    coversTo: MatchClock
    summary: str
    statsTime: Optional[MatchClock]
    model: Optional[str]
    promptVersion: Optional[str]
    tokens: Optional[dict]
    createdAt: str
    supersededBy: Optional[str] = None
    tier: Optional[str] = None  # minute, five-minute, twenty-minute or half (a whole period)


@dataclass
class Narrative:
    id: str
    matchId: str
    userType: str
    seq: int
    stepId: str
    trigger: Trigger
    matchTime: MatchClock
    text: str
    model: Optional[str]
    promptVersion: Optional[str]
    tokens: Optional[dict]
    createdAt: str
    timeSec: Optional[int] = None           # second of `matchTime` the step's data reaches
    audienceRevision: Optional[int] = None  # user-backend audience revision the bucket came from
    eventSeq: Optional[int] = None          # latest canonical MatchEvent seq in the data it was written from
    analysisId: Optional[str] = None        # the match analysis (storyline state) the step read
    storylineIds: list = field(default_factory=list)  # the storyline it advances (the step's focus), if any
    kind: str = "bucket"                    # or "subscription": a followed topic's narrative for one bucket
    topicId: Optional[str] = None           # subscription only
    decision: Optional[dict] = None         # subscription only: score, confidence, novelty, model of the trigger


class BrokerUnavailable(RuntimeError):
    """The narrative broker is throttling or unreachable: the step waits and retries, it is not a fault."""
