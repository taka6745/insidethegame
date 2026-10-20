"""Match clock, audience buckets and the ETL notification messages.

The clock follows the ETL's Opta convention (see etl/contracts/README.md): `timeMin` is
0-based, first-half added time keeps counting (46 = 45+2') and the second half restarts
at 45, so a minute is only unique together with its period.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

PERIOD_START = {1: 0, 2: 45, 3: 90, 4: 105}
PERIOD_END = {1: 45, 2: 90, 3: 105, 4: 120}

SUPPORT = ("home", "away", "neutral")
LEVELS = ("simple", "casual", "experienced", "analyst")
USER_TYPES = tuple(f"{s}:{l}" for s in SUPPORT for l in LEVELS)

KEY_TYPES = ("Goal", "OwnGoal", "PenaltyAwarded", "PenaltyMissed", "RedCard", "VarOverturn")


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


@dataclass(frozen=True)
class PresenceChanged:
    matchId: str
    activeUserTypes: dict
    sentAt: datetime

    @property
    def active(self):
        return frozenset(t for t, n in self.activeUserTypes.items() if n > 0 and t in USER_TYPES)


def parse_notification(body, message_type=None):
    """Turn a Service Bus body (plus its `messageType` user property) into a message.

    Local replays carry `messageType` in the body; Service Bus carries it as a user
    property. Returns None for types the engine does not handle.
    """
    kind = message_type or body.get("messageType")
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
    if kind in ("PeriodStarted", "PeriodEnded"):
        return PeriodChanged(match_id, int(body["periodId"]), kind == "PeriodStarted", parse_time(body["eventTime"]))
    if kind == "PresenceChanged":
        counts = {t: int(n) for t, n in body.get("activeUserTypes", {}).items()}
        return PresenceChanged(match_id, counts, parse_time(body["sentAt"]))
    return None


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
    type: str  # keyEvent, scheduled, halfTime, fullTime, catchUp
    ref: str
    reason: str
    eventIds: tuple = ()


@dataclass(frozen=True)
class AgentResult:
    text: str
    model: Optional[str] = None
    promptVersion: Optional[str] = None
    tokens: Optional[dict] = None


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
