from collections import Counter
from datetime import datetime, timezone

from etltools import opta, pipeline
from seeder.generate import MatchBuilder
from seeder.replay import schedule

MATCH = MatchBuilder("test-match", seed=7).build()


def test_generation_is_deterministic_and_labelled():
    again = MatchBuilder("test-match", seed=7).build()
    assert again == MATCH
    assert all(m["synthetic"] for m in MATCH)
    assert MATCH[0]["feed"] == "MA1" and "SYNTHETIC" in MATCH[0]["provenance"]
    ids = [m["id"] for m in MATCH[1:]]
    assert len(ids) == len(set(ids))


def test_every_key_event_type_appears():
    keys = Counter(opta.key_event(m) for m in MATCH[1:] if opta.key_event(m))
    assert keys == Counter({
        ("Goal", None): 2, ("Goal", "penalty"): 1, ("OwnGoal", None): 1,
        ("PenaltyAwarded", "conceded"): 2, ("PenaltyMissed", None): 1,
        ("RedCard", "second-yellow"): 1, ("VarOverturn", "goal-overturned"): 1,
    })


def test_final_score_accounts_for_var_and_own_goal():
    out = pipeline.stream_outputs(MATCH, window=60)
    rows = pipeline.stats_as_of(out["minuteStats"], out["matches"])
    last = max((r["periodId"], r["timeMin"]) for r in rows)
    final = {r["position"]: r for r in rows if (r["periodId"], r["timeMin"]) == last}
    assert (final["home"]["goals"], final["away"]["goals"]) == (1, 2)
    assert final["home"]["ownGoals"] == 1 and final["home"]["redCards"] == 1
    assert abs(final["home"]["possessionPct"] + final["away"]["possessionPct"] - 100) <= 0.1


def test_replay_puts_each_match_minute_in_its_own_window():
    start = datetime(2026, 10, 18, 4, 0, 7, tzinfo=timezone.utc)
    for speed in (1, 10, 12, 60):
        window = int(60 / speed)
        replay = schedule(MATCH, "replay", speed, half_time_seconds=30, start=start)
        minutes_per_window = Counter()
        seen = set()
        for m in replay[1:]:
            end = pipeline.window_end(pipeline.parse_time(m["timeStamp"]), window)
            if (end, m["periodId"], m["timeMin"]) not in seen:
                seen.add((end, m["periodId"], m["timeMin"]))
                minutes_per_window[end] += 1
        assert max(minutes_per_window.values()) == 1, f"speed {speed}"
        assert all(m["matchId"] == "replay" for m in replay)


def test_period_notifications_are_deduplicated():
    out = pipeline.stream_outputs(MATCH, window=60)
    kinds = Counter(n["messageType"] for n in out["notifications"])
    assert kinds["PeriodStarted"] == 2 and kinds["PeriodEnded"] == 2
    assert kinds["KeyEventDetected"] == 9


def test_minute_labels():
    assert opta.minute_label(1, 0) == "1'"
    assert opta.minute_label(1, 44) == "45'"
    assert opta.minute_label(1, 46) == "45+2'"
    assert opta.minute_label(2, 45) == "46'"
    assert opta.minute_label(2, 93) == "90+4'"
