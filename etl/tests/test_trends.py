"""reference/trends.py: rules on small hand-built inputs, plus Riverton Rovers–United against fixtures/trends-golden.json.

The golden file holds full-time and half-time trends and spells (rounded) and the recording's hash. Regenerate after
a deliberate rule or seed change, or after the recordings are re-rendered (the test names the cause):
    python tests/test_trends.py --regenerate
SQL parity on every recording is in test_sql_trends.py.
"""
import hashlib
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from reference import trends  # noqa: E402
import v2_stream  # noqa: E402
from test_catalogue import outputs  # noqa: E402

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "trends-golden.json"
RECORDING = v2_stream.RECORDINGS / "riverton-forgeham-grf.opta-stream.jsonl"
MATCH = {"matchId": "m", "homeContestantId": "home", "awayContestantId": "away"}


def events(minutes, period=1):
    """One canonical event per 10 s of the given minutes (clock = video)."""
    base = 0 if period == 1 else 2700
    return [{"seq": 0, "periodId": period, "matchTimeSeconds": base + 60 * m + s, "videoSeconds": float(base + 60 * m + s)}
            for m in minutes for s in range(0, 60, 10)]


def numbered(rows):
    for i, r in enumerate(rows, 1):
        r["seq"] = i
    return rows


def act(i, team, clock, sx, ex=None, typ="pass", result="success", poss=1, sy=34.0, ey=34.0, period=1):
    """A SPADL action with x given in the acting team's frame (stored in SPADL's home frame); y as stored."""
    ex = sx if ex is None else ex
    flip = (lambda x: x) if team == "home" else (lambda x: 105.0 - x)
    return {"actionId": i, "finalSeq": 0, "periodId": period, "teamId": team, "timeSeconds": float(clock),
            "clockSeconds": float(clock), "startX": flip(sx), "endX": flip(ex), "startY": sy, "endY": ey,
            "typeName": typ, "resultName": result, "possessionId": poss}


def raw(team, clock, type_id, x, outcome=1):
    return {"eventSeq": 0, "contestantId": team, "typeId": type_id, "outcome": outcome, "x": x, "periodId": 1,
            "timeMin": clock // 60, "timeSec": clock % 60}


def call(fn, ev, samples=(), actions=(), raws=(), seq=None, defs=None):
    seq = len(ev) if seq is None else seq
    return fn(MATCH, ev, list(samples), seq, len(ev), defs, actions=list(actions), raw=list(raws))


def by_minute(rows, team="home"):
    return {r["minute"]: r for r in rows if r["contestantId"] == team}


def enabled(*ids):
    return [{**d, "enabled": d["trendId"] in ids} for d in trends.definitions()]


def test_ball_time_holds_until_the_next_action_capped_and_split_at_minute_ends():
    ev = numbered(events([0, 1]))
    acts = [act(0, "home", 55, 80), act(1, "away", 62, 25), act(2, "home", 90, 10)]
    rows = call(trends.trend_minutes_at_seq, ev, actions=acts)
    home, away = by_minute(rows), by_minute(rows, "away")
    # 55-60 s and 60-62 s at home x 80; 62-70 s (capped at 8 s) at away x 25 (home x 80); 90-91 s at home x 10.
    assert (home[0]["ballSeconds"], home[0]["attHalfSeconds"], home[0]["finalThirdSeconds"]) == (5, 5, 5)
    assert (home[1]["ballSeconds"], home[1]["attHalfSeconds"], home[1]["finalThirdSeconds"]) == (11, 10, 10)
    assert (away[1]["ballSeconds"], away[1]["attHalfSeconds"]) == (11, 1)
    assert home[1]["attHalfShare"] == (10 + 1) / (11 + 2)


def test_entries_count_once_per_possession_and_fast_breaks_need_pace_and_progress():
    ev = numbered(events([0, 1]))
    acts = [act(0, "home", 1, 30, 75, poss=1), act(1, "home", 3, 75, 95, poss=1),  # break: 45 m in 2 s, box entry
            act(2, "home", 4, 60, 80, poss=1),  # second entry of possession 1: not counted
            act(3, "home", 20, 65, 85, poss=2),  # entry, but starts in the opponent's half: no break
            act(4, "home", 70, 20, 40, poss=3), act(5, "home", 83, 40, 90, poss=3),  # 50 m, but after 13 s
            act(6, "away", 100, 50, 90, typ="cross", result="fail", poss=4)]
    rows = call(trends.trend_minutes_at_seq, ev, actions=acts)
    home = by_minute(rows)
    assert (home[0]["ftEntries"], home[0]["boxEntries"], home[0]["fastBreaks"]) == (2, 1, 1)
    assert (home[1]["ftEntries"], home[1]["fastBreaks"]) == (1, 0)
    assert home[0]["ftActions"] == 1 and by_minute(rows, "away")[1]["passes"] == 1


def test_ma3_rows_give_pressing_defence_fouls_and_cards():
    ev = numbered(events([0]))
    raws = [raw("home", 5, 7, 50.0), raw("home", 6, 4, 30.0, outcome=0), raw("home", 7, 12, 10.0),
            raw("home", 8, 17, None), raw("away", 9, 1, 50.0), raw("away", 10, 1, 70.0), raw("away", 11, 7, None)]
    home = by_minute(call(trends.trend_minutes_at_seq, ev, raws=raws))[0]
    # Tackle at 52.5 m presses; the foul at 31.5 m does not; the clearance only counts for height.
    assert (home["pressActions"], home["defActions"], home["defHeight"]) == (1, 3, (52.5 + 31.5 + 10.5) / 3)
    assert (home["fouls"], home["cards"], home["tackles"]) == (1, 1, 1)
    assert by_minute(call(trends.trend_minutes_at_seq, ev, raws=raws), "away")[0]["buildPasses"] == 1
    ppda = {r["contestantId"]: r["value"] for r in call(trends.trends_at_seq, ev, raws=raws)
            if r["trendId"] == "ppda" and r["window"] == "match"}
    assert ppda == {"home": (1 + 1) / (1 + 1), "away": (0 + 1) / (0 + 1)}


def possession_match(home_share_last5):
    """20 minutes; each minute has 50 owned seconds, split 50/50 except the last five."""
    ev = numbered(events(range(20)))
    samples = [{"videoSeconds": 60.0 * m + 30, "durationSeconds": 50 * (share if m >= 15 else 0.5), "contestantId": t}
               for m in range(20) for t, share in (("home", home_share_last5), ("away", 1 - home_share_last5))]
    return ev, samples


def test_windows_baselines_and_flags():
    ev, samples = possession_match(0.9)
    rows = call(trends.trends_at_seq, ev, samples)
    poss = {r["window"]: r for r in rows if r["trendId"] == "possession" and r["contestantId"] == "home"}
    assert [r["window"] for r in rows if r["trendId"] == "possession" and r["contestantId"] == "home"] == trends.WINDOWS
    assert (poss["last5"]["minutes"], poss["last5"]["fromLabel"], poss["last5"]["toLabel"]) == (5, "16'", "20'")
    assert poss["last5"]["value"] == (225 + 1) / (250 + 2) and poss["last5"]["baseline"] == poss["prev10"]["value"] == 0.5
    assert (poss["last5"]["level"], poss["last5"]["change"], poss["last5"]["flagged"]) == ("high", "rising", True)
    assert poss["prev10"]["level"] is None and poss["match"]["baseline"] is None and poss["half"]["delta"] is None
    away = next(r for r in rows if r["trendId"] == "possession" and r["contestantId"] == "away" and r["window"] == "last5")
    assert (away["level"], away["change"]) == (None, "falling")
    # Disabled: values stay, flags go. A window short of its length never flags.
    quiet = call(trends.trends_at_seq, ev, samples, defs=enabled())
    assert not any(r["flagged"] or r["level"] or r["change"] for r in quiet)
    assert [r["value"] for r in quiet] == [r["value"] for r in rows]
    # 19 minutes: last5 = 15'-19' (four of them at 0.9) against a full prev10; a change of 0.3 flags at 0.3.
    defs = [{**d, "changeAt": 0.3} if d["trendId"] == "possession" else d for d in trends.definitions()]
    early = call(trends.trends_at_seq, *possession_match(0.9), seq=6 * 19, defs=defs)
    assert next(r for r in early if r["trendId"] == "possession" and r["window"] == "last5")["change"] == "rising"
    ev4 = numbered(events(range(4)))
    short = call(trends.trends_at_seq, ev4, [{"videoSeconds": 30.0, "durationSeconds": 50, "contestantId": "home"}])
    assert next(r for r in short if r["trendId"] == "possession" and r["window"] == "last5")["level"] is None


def test_spells_bridge_single_minutes_within_a_period():
    flagged = [1, 1, 0, 1, 0, 0, 1, 1]  # home: minutes 0-3 are one spell (2 bridged), 6-7 too short
    ev, acts = numbered(events(range(len(flagged)))), []
    for m, f in enumerate(flagged):
        for s in range(0, 60, 6):
            acts.append({**act(len(acts), "home", 60 * m + s, 90 if f else 20, typ="dribble", result="fail"),
                         "finalSeq": 6 * m + 1})
    defs = enabled("territory_spell")
    spell, away = call(trends.spells_at_seq, ev, actions=acts, defs=defs)
    assert (away["contestantId"], away["fromLabel"], away["toLabel"]) == ("away", "3'", "6'")  # the ball at its x 85
    assert spell == {"trendId": "territory_spell", "contestantId": "home", "periodId": 1, "fromLabel": "1'",
                     "toLabel": "4'", "minutes": 4, "zoneShare": 180 / 240, "shots": 0, "boxEntries": 0,
                     "ongoing": False, "enabled": True}
    assert call(trends.spells_at_seq, ev, actions=acts, seq=6 * 4, defs=defs)[0]["ongoing"] is True


def test_flanks_split_the_attacking_half_by_width_in_the_team_frame():
    ev = numbered(events([0]))
    acts = [act(0, "home", 5, 80, sy=10.0), act(1, "home", 10, 80, sy=60.0), act(2, "home", 15, 30, sy=10.0),
            act(3, "away", 20, 80, sy=58.0)]  # stored in the home frame: y 10 in away's own frame, its right
    home, away = by_minute(call(trends.trend_minutes_at_seq, ev, actions=acts))[0], \
        by_minute(call(trends.trend_minutes_at_seq, ev, actions=acts), "away")[0]
    assert (home["attActions"], home["rightActions"], home["leftActions"]) == (2, 1, 1)
    assert (away["attActions"], away["rightActions"]) == (1, 1)
    rows = {(r["trendId"], r["contestantId"]): r["value"] for r in call(trends.trends_at_seq, ev, actions=acts)
            if r["window"] == "match"}
    assert rows[("right_flank_share", "home")] == (1 + 1) / (2 + 2) and rows[("right_flank_share", "away")] == 2 / 3


def test_game_state_counts_own_goals_and_var_overturns():
    ev = numbered(events(range(12)))
    acts = [act(0, "home", 70, 95, typ="shot"), act(1, "away", 190, 5, typ="bad_touch", result="owngoal"),
            act(2, "away", 300, 95, typ="shot")]
    var = {**raw("away", 330, 900, None), "qualifier": [{"qualifierId": 901, "value": "goal-overturned"}]}
    rows = by_minute(call(trends.trend_minutes_at_seq, ev, actions=acts, raws=[var]))
    # Home scores at 1', away puts one in its own net at 3'; away's goal at 5' is overturned at 5'.
    assert [rows[m]["leadAtStart"] for m in (0, 1, 2, 3, 4, 5, 6)] == [0, 0, 1, 1, 2, 2, 2]
    assert by_minute(call(trends.trend_minutes_at_seq, ev, actions=acts, raws=[var]), "away")[6]["leadAtStart"] == -2
    served = {(r["trendId"], r["contestantId"]): r for r in call(trends.trends_at_seq, ev, actions=acts, raws=[var])}
    lead, trail = served[("att_half_leading", "home")], served[("att_half_trailing", "away")]
    assert (lead["window"], lead["minutes"], trail["window"]) == ("half", 12, "half")
    assert lead["value"] is not None and served[("att_half_trailing", "home")]["value"] is None  # never behind


def test_fade_compares_last15_with_the_15_minutes_before_it():
    ev = numbered(events(range(30)))
    acts = [{**act(m, "home", 60 * m + 1, 80 if m < 15 else 20), "finalSeq": 6 * m + 1} for m in range(30)]
    fade = next(r for r in call(trends.trends_at_seq, ev, actions=acts)
                if r["trendId"] == "territory_fade" and r["contestantId"] == "home")
    # 8 s of ball a minute (the gap cap; 1 s after the last action): all in the attacking half, then none.
    assert (fade["window"], fade["value"]) == ("last15", (120 + 1) / (120 + 2) - (0 + 1) / (113 + 2))
    short = call(trends.trends_at_seq, ev, actions=acts, seq=6 * 29)
    assert next(r for r in short if r["trendId"] == "territory_fade")["value"] is None


def test_low_direction_flags_at_or_below_and_spells_can_require_another():
    ev, samples = possession_match(0.1)
    defs = [{**d, "direction": "low", "notableAt": 0.3, "highAt": 0.2} if d["trendId"] == "possession" else d
            for d in trends.definitions()]
    last5 = next(r for r in call(trends.trends_at_seq, ev, samples, defs=defs)
                 if r["trendId"] == "possession" and r["window"] == "last5" and r["contestantId"] == "home")
    assert last5["level"] == "high"
    flagged = [1, 1, 1, 1, 0, 0, 0, 0]
    ev = numbered(events(range(8)))
    acts = [{**act(10 * m + i, "home", 60 * m + 6 * i, 90 if f else 20, typ="shot" if f and i == 0 else "dribble",
                   result="fail"), "finalSeq": 6 * m + 1} for m, f in enumerate(flagged) for i in range(10)]
    spells = {r["trendId"]: r for r in call(trends.spells_at_seq, ev, actions=acts)}
    assert spells["pressure_spell"]["enabled"] is True  # it overlaps the territory spell
    alone = [{**d, "minuteAt": 2.0} if d["trendId"] == "territory_spell" else d for d in trends.definitions()]
    spells = {r["trendId"]: r for r in call(trends.spells_at_seq, ev, actions=acts, defs=alone)}
    assert "territory_spell" not in spells and spells["pressure_spell"]["enabled"] is False


def test_momentum_is_an_ewma_of_the_threat_difference():
    ev = numbered(events(range(3)))
    acts = [act(0, "home", 10, 80, typ="shot", result="fail"), act(1, "away", 130, 40, typ="shot", result="fail")]
    rows = by_minute(call(trends.trend_minutes_at_seq, ev, actions=acts))
    th = rows[0]["threat"]
    assert th == 0.02 * 8 + 3  # 8 s in the final third (gap capped), then the shot
    assert rows[0]["momentum"] == 0.4 * th and rows[1]["momentum"] == 0.6 * rows[0]["momentum"]
    assert by_minute(call(trends.trend_minutes_at_seq, ev, actions=acts), "away")[0]["momentum"] == -0.4 * th


def test_snapshot_bounds():
    ev = numbered(events([0]))
    for fn in (trends.trend_minutes_at_seq, trends.trends_at_seq, trends.spells_at_seq):
        assert fn(MATCH, ev, [], len(ev) + 1, len(ev), actions=[], raw=[]) == []
        assert fn(None, [], [], 0, 0, actions=[], raw=[]) == [] and call(fn, [], seq=0) == []


def test_the_newest_seed_block_wins(tmp_path, monkeypatch):
    first = (trends.MIGRATIONS / "011_trend_definitions.sql").read_text(encoding="utf-8")
    (tmp_path / "011_trend_definitions.sql").write_text(first, encoding="utf-8")
    block = json.dumps([{**d, "enabled": True} for d in trends.definitions()[:2]])
    (tmp_path / "099_trend_seed.sql").write_text(
        f"DECLARE @trendDefinitions nvarchar(max) = N'{block}';\nEXEC dbo.seedTrendDefinitions @trendDefinitions;\n")
    monkeypatch.setattr(trends, "MIGRATIONS", tmp_path)
    assert [(d["trendId"], d["enabled"]) for d in trends.definitions()] == [("possession", True), ("field_tilt", True)]


def compact(rows):
    return [[r[k] if not isinstance(r[k], float) else round(r[k], 6) for k in r] for r in rows]


def snapshots():
    stream = v2_stream.build()
    rows = outputs(stream)
    final = len(rows["canonicalEvents"])
    half_time = max(e["seq"] for e in rows["canonicalEvents"] if e["periodId"] == 1)
    out = {}
    for seq in (half_time, final):
        args = (rows["matches"][0], rows["canonicalEvents"], rows["possessionSamples"], seq, final)
        kw = {"actions": rows["spadlActions"], "raw": rows["rawEvents"]}
        out[str(seq)] = {"trends": compact([r for r in trends.trends_at_seq(*args, **kw) if r["window"] in ("half", "last5")]),
                         "spells": compact(trends.spells_at_seq(*args, **kw))}
    return out


def recording_hash():
    return hashlib.sha256(RECORDING.read_bytes()).hexdigest()


def test_riverton_united_equals_golden():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if golden["recording"] != recording_hash():
        pytest.fail("riverton-forgeham recording changed: python tests/test_trends.py --regenerate")
    assert snapshots() == golden["snapshots"]


if __name__ == "__main__" and "--regenerate" in sys.argv:
    GOLDEN_PATH.write_text(json.dumps({"recording": recording_hash(), "snapshots": snapshots()}, separators=(",", ":")),
                           encoding="utf-8")
    print(f"wrote {GOLDEN_PATH}")
