"""Message parsing against real ETL output.

The fixture is etl/.local/notifications.jsonl from the ETL's `python -m devtools load-local` for the
synthetic match itg-syn-0001 (generated data, not a real match).
"""
import json
from collections import Counter
from pathlib import Path

from narrative_engine.core.models import (USER_TYPES, KeyEventDetected, MatchClock, MinuteClosed, PeriodChanged,
                                     PresenceChanged, parse_notification)

FIXTURES = Path(__file__).parent / "fixtures"


def notifications():
    with open(FIXTURES / "itg-syn-0001-notifications.jsonl") as f:
        return [json.loads(line) for line in f]


def test_every_etl_notification_parses():
    parsed = [parse_notification(n) for n in notifications()]
    kinds = Counter(type(m).__name__ for m in parsed)
    assert kinds == {"MinuteClosed": 98, "KeyEventDetected": 9, "PeriodChanged": 4}
    keys = Counter(m.keyType for m in parsed if isinstance(m, KeyEventDetected))
    assert keys == {"Goal": 3, "PenaltyAwarded": 2, "PenaltyMissed": 1, "VarOverturn": 1, "RedCard": 1, "OwnGoal": 1}


def test_string_related_event_id_becomes_int():
    var = next(parse_notification(n) for n in notifications() if n.get("keyType") == "VarOverturn")
    assert var.relatedEventId == 405 and var.clock == MatchClock(2, 53)


def test_message_type_can_come_from_the_user_property():
    body = {"matchId": "m", "periodId": 2, "timeMin": 70, "windowEnd": "2026-10-18T07:35:12+00:00"}
    assert parse_notification(body, "MinuteClosed") == MinuteClosed("m", MatchClock(2, 70),
                                                                     parse_notification(body, "MinuteClosed").windowEnd)
    period = parse_notification({"matchId": "m", "periodId": 1, "eventTime": "2026-10-18T07:32:02.850Z"}, "PeriodEnded")
    assert period == PeriodChanged("m", 1, False, period.eventTime)
    assert parse_notification({"matchId": "m"}, "SomethingElse") is None


def test_labels_follow_the_etl_minute_label():
    assert MatchClock(1, 0).label == "1'"
    assert MatchClock(1, 44).label == "45'"
    assert MatchClock(1, 46).label == "45+2'"
    assert MatchClock(2, 45).label == "46'"
    assert MatchClock(2, 90).label == "90+1'"
    assert MatchClock.parse(MatchClock(2, 7).key) == MatchClock(2, 7)


def test_presence_keeps_only_known_active_buckets():
    msg = parse_notification({"messageType": "PresenceChanged", "matchId": "m", "sentAt": "2026-10-18T07:00:00Z",
                              "activeUserTypes": {"home:casual": 2, "away:analyst": 0, "martian:simple": 4}})
    assert isinstance(msg, PresenceChanged) and msg.active == {"home:casual"}
    assert len(USER_TYPES) == 12 and len(set(USER_TYPES)) == 12


def test_minutes_between_crosses_half_time_once_the_period_end_is_known():
    from narrative_engine.core.models import minutes_between
    ends = {1: MatchClock(1, 47)}
    assert minutes_between(MatchClock(1, 45), MatchClock(2, 46), ends.get) == [
        MatchClock(1, 46), MatchClock(1, 47), MatchClock(2, 45), MatchClock(2, 46)]
    assert minutes_between(MatchClock(1, 45), MatchClock(2, 46), {}.get) is None
    assert minutes_between(None, MatchClock(1, 1), {}.get) == [MatchClock(1, 0), MatchClock(1, 1)]
    assert minutes_between(MatchClock(1, 5), MatchClock(1, 3), {}.get) == []


def test_bodies_with_every_key_and_nulls_parse():
    """Since 18 Oct the ETL sends every notification key on every message, unused ones null."""
    keys = ("messageType messageId matchId periodId timeMin timeSec eventTime windowEnd id keyType detail typeId "
            "contestantId playerId relatedEventId").split()
    blank = dict.fromkeys(keys)
    minute = parse_notification({**blank, "messageType": "MinuteClosed", "matchId": "m", "periodId": 1, "timeMin": 4,
                                 "windowEnd": "2026-10-18T07:27:48+00:00"})
    assert isinstance(minute, MinuteClosed) and minute.clock == MatchClock(1, 4)
    period = parse_notification({**blank, "messageType": "PeriodEnded", "matchId": "m", "periodId": 1,
                                 "eventTime": "2026-10-18T07:32:02.850Z"})
    assert isinstance(period, PeriodChanged) and not period.started
    key = parse_notification({**blank, "messageType": "KeyEventDetected", "matchId": "m", "id": 7, "keyType": "Goal",
                              "typeId": 16, "contestantId": "c", "periodId": 1, "timeMin": 3, "timeSec": 2,
                              "eventTime": "2026-10-18T07:27:40Z", "relatedEventId": 405})
    assert isinstance(key, KeyEventDetected) and key.relatedEventId == 405 and key.detail is None
