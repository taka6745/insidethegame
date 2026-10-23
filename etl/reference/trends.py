"""Python twin of dbo.trendMinuteRows, trendMinutesAtSeq, trendsAtSeq and trendSpellsAtSeq; tests compare them.

Configuration comes from the newest `@trendDefinitions`/`@trendParameters` seed blocks in sql/migrations.
Conventions: team frame (the team attacks towards x = 105); a minute is (periodId, floor(clock / 60)); shares
carry a +1 prior; rates are per 5 minutes.
"""
import json
import math
import re
from bisect import bisect_right
from pathlib import Path

from reference.opta import minute_label, qualifiers as _qualifiers

MIGRATIONS = Path(__file__).resolve().parents[1] / "sql" / "migrations"
SEED = re.compile(r"@trendDefinitions nvarchar\(max\) = N'(.*?)';", re.S)
PARAMETERS = re.compile(r"@trendParameters nvarchar\(max\) = N'(.*?)';", re.S)
LABELS = re.compile(r"@trendLabels nvarchar\(max\) = N'(.*?)';", re.S)

L, W = 105.0, 68.0
HALF, FINAL, BOX_X, BOX_HALF_WIDTH = 52.5, 70.0, 88.5, 20.16
EPS = 1e-9
PASSES = {"pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short",
          "goalkick"}
SET_PIECES = {"throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short", "goalkick"}
SHOTS = {"shot", "shot_penalty", "shot_freekick"}
DEFENSIVE, DEF_EXTRA = {7, 8, 45}, {12, 49, 74}  # MA3: tackle, interception, challenge; clearance, recovery, block
FOUL, CARD, TACKLE, CHALLENGE, AERIAL, TAKE_ON, PASS = 4, 17, 7, 45, 44, 3, 1
WINDOWS = ["last5", "last15", "prev10", "half", "match"]  # served, in this order
BASELINE = {"last5": "prev10", "last15": "pre15", "half": "prevHalf"}
FULL = {"last5": 5, "prev10": 10, "last15": 15, "half": 5, "match": 5}  # minutes a window needs to flag
# Trends served in one window only: the late fade (last15 against the 15 minutes before it, same period) and
# territory by game state (this half's minutes the team started ahead or behind).
SINGLE = {"territory_fade": "last15", "att_half_leading": "half", "att_half_trailing": "half"}
MIN_BASELINE = 10  # minutes a baseline needs for a change flag

COUNTS = ["ftActions", "ftEntries", "boxEntries", "shots", "boxShots", "buildPasses", "pressActions", "defActions",
          "fouls", "cards", "tackles", "challenges", "aerials", "takeOns", "fastBreaks", "passes", "longPasses",
          "attActions", "rightActions", "leftActions", "goalsFor"]
SECONDS = ["possessionSeconds", "ballSeconds", "attHalfSeconds", "finalThirdSeconds", "defMetres", "forwardMetres",
           "passMetres"]
MINUTE_COLUMNS = ["periodId", "minute", "minuteLabel", "contestantId", "possessionSeconds", "ballSeconds",
                  "attHalfSeconds", "finalThirdSeconds", "attHalfShare", "finalThirdShare", "ftActions", "ftEntries",
                  "boxEntries", "shots", "boxShots", "buildPasses", "pressActions", "defActions", "defHeight", "fouls",
                  "cards", "tackles", "challenges", "aerials", "takeOns", "fastBreaks", "passes", "forwardMetres",
                  "passMetres", "longPasses", "threat", "momentum", "territoryMinute", "pressureMinute",
                  "attActions", "rightActions", "leftActions", "goalsFor", "leadAtStart"]
GOAL_OVERTURNED, OWN_GOAL, VAR = "goal-overturned", 28, 900


def definitions():
    """The seeded trendDefinitions rows, in displayOrder: the newest seed block in sql/migrations, with the label
    updates (`@trendLabels`) of later migrations applied in order."""
    seeds, labels = [], {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        if found := [m.group(1) for m in SEED.finditer(text)]:
            seeds, labels = found, {}
        for m in LABELS.finditer(text):
            labels.update({r["trendId"]: r["label"] for r in json.loads(m.group(1).replace("''", "'"))})
    rows = json.loads(seeds[-1].replace("''", "'"))
    return [{**row, "label": labels.get(row["trendId"], row["label"]), "displayOrder": i + 1}
            for i, row in enumerate(rows)]


def parameters():
    """The seeded trendParameters (name -> value): the newest seed block in sql/migrations."""
    blocks = [m.group(1) for path in sorted(MIGRATIONS.glob("*.sql"))
              for m in PARAMETERS.finditer(path.read_text(encoding="utf-8"))]
    return {row["name"]: float(row["value"]) for row in json.loads(blocks[-1].replace("''", "'"))}


def _in_box(x, y):
    return x >= BOX_X and abs(y - W / 2) <= BOX_HALF_WIDTH


def _share(a, b):
    return (a + 1) / (a + b + 2)


def minute_rows(match, events, samples, seq, watermark, defs=None, *, actions, raw, params=None):
    """dbo.trendMinuteRows: per minute (in match order) and team (home first), the components every trend
    reads, with momentum and the spell minute flags. Empty when seq is outside 0..watermark
    (watermark = min(matchWatermarks.seq, spadlSeq))."""
    if match is None or not 0 <= seq <= watermark:
        return []
    home, away = match["homeContestantId"], match["awayContestantId"]
    defs = {d["trendId"]: d for d in (defs or definitions())}
    p = params or parameters()
    lane = W / p["flank_lanes"]  # flanks: the outer lanes of the width (team frame: y = 0 is the right touchline)
    comp = {}

    def c(key, is_home):
        return comp.setdefault(key, {True: dict.fromkeys(COUNTS + SECONDS, 0), False: dict.fromkeys(COUNTS + SECONDS, 0)})[is_home]

    # Minutes the clock has reached; each starts at its first event's video time.
    starts = {}
    for e in events:
        if e["seq"] <= seq:
            key = (e["periodId"], e["matchTimeSeconds"] // 60)
            c(key, True)
            if e["videoSeconds"] is not None and (key not in starts or e["videoSeconds"] < starts[key]):
                starts[key] = e["videoSeconds"]
    video = max((e["videoSeconds"] for e in events if e["seq"] <= seq and e["videoSeconds"] is not None), default=None)

    # Possession: each sample up to the snapshot's video time counts in the minute it ends in.
    ordered = sorted(starts, key=lambda k: starts[k])
    times = [starts[k] for k in ordered]
    for s in samples:
        if video is not None and s["videoSeconds"] <= video and s["contestantId"] in (home, away) and ordered:
            key = ordered[max(bisect_right(times, s["videoSeconds"]) - 1, 0)]
            c(key, s["contestantId"] == home)["possessionSeconds"] += s["durationSeconds"]

    acts = sorted((a for a in actions if a["finalSeq"] <= seq), key=lambda a: a["actionId"])
    frame = []
    for a in acts:
        h = a["teamId"] == home
        frame.append({"key": (a["periodId"], math.floor(a["clockSeconds"] / 60)), "home": h,
                      "sx": a["startX"] if h else L - a["startX"], "sy": a["startY"] if h else W - a["startY"],
                      "ex": a["endX"] if h else L - a["endX"], "ey": a["endY"] if h else W - a["endY"]})

    # Ball timeline: each action's start holds until the next action (same period), split at minute ends.
    for i, a in enumerate(acts):
        nxt = acts[i + 1] if i + 1 < len(acts) and acts[i + 1]["periodId"] == a["periodId"] else None
        dur = min(nxt["timeSeconds"] - a["timeSeconds"], p["ball_gap_cap_seconds"]) if nxt else p["ball_last_gap_seconds"]
        if dur <= 0:
            continue
        start = a["clockSeconds"]
        end, m0 = start + dur, math.floor(start / 60)
        boundary = (m0 + 1) * 60
        pieces = [(m0, min(end, boundary) - start), (m0 + 1, end - boundary if boundary < end - EPS else 0.0)]
        for minute, s in pieces:
            if s <= 0:
                continue
            for is_home in (True, False):
                x = a["startX"] if is_home else L - a["startX"]
                cc = c((a["periodId"], minute), is_home)
                cc["ballSeconds"] += s
                cc["attHalfSeconds"] += s if x >= HALF else 0
                cc["finalThirdSeconds"] += s if x >= FINAL else 0

    # On-ball actions; entries count once per (period, possession, team).
    entered = set()
    for a, f in zip(acts, frame):
        cc, typ, ok = c(f["key"], f["home"]), a["typeName"], a["resultName"] == "success"
        sx, sy, ex, ey = f["sx"], f["sy"], f["ex"], f["ey"]
        if sx >= FINAL and typ != "foul":
            cc["ftActions"] += 1
        if sx >= HALF and typ != "foul":
            cc["attActions"] += 1
            cc["rightActions"] += sy < lane
            cc["leftActions"] += sy > W - lane
        if typ in SHOTS and ok:
            cc["goalsFor"] += 1
        if a["resultName"] == "owngoal":  # counts for the opponent
            c(f["key"], not f["home"])["goalsFor"] += 1
        if typ in PASSES | {"dribble"} and ok:
            pos = (a["periodId"], a["possessionId"], f["home"])
            if sx < FINAL <= ex and (pos, "ft") not in entered:
                entered.add((pos, "ft"))
                cc["ftEntries"] += 1
            if not _in_box(sx, sy) and _in_box(ex, ey) and (pos, "box") not in entered:
                entered.add((pos, "box"))
                cc["boxEntries"] += 1
        if typ in SHOTS:
            cc["shots"] += 1
            cc["boxShots"] += _in_box(sx, sy)
        if typ in PASSES - SET_PIECES:
            length = math.sqrt((ex - sx) * (ex - sx) + (ey - sy) * (ey - sy))
            cc["passes"] += 1
            cc["forwardMetres"] += max(0.0, ex - sx)
            cc["passMetres"] += length
            cc["longPasses"] += length >= p["long_pass_metres"]

    # Fast breaks: an open-play possession from the own half reaching the final third with fast_break_metres of
    # progress (or a shot) within fast_break_seconds; counted in its first action's minute.
    groups = {}
    for a, f in zip(acts, frame):
        if a["possessionId"] is not None:
            groups.setdefault((a["periodId"], a["possessionId"], f["home"]), []).append((a, f))
    for chain in groups.values():
        first, ff = chain[0]
        if first["typeName"] in SET_PIECES or ff["sx"] >= HALF:
            continue
        x0, t0 = ff["sx"], first["timeSeconds"]
        for a, f in chain:
            if a["timeSeconds"] - t0 > p["fast_break_seconds"]:
                break
            ok = a["resultName"] == "success" and a["typeName"] in PASSES | {"dribble", "take_on"}
            reach = f["ex"] if ok and f["ex"] > f["sx"] else f["sx"]
            if (reach >= FINAL and reach - x0 >= p["fast_break_metres"]) or a["typeName"] in SHOTS:
                c(ff["key"], ff["home"])["fastBreaks"] += 1
                break

    # MA3 rows outside SPADL (Opta x is already team-relative, 0-100).
    for r in raw:
        if r["eventSeq"] is None or r["eventSeq"] > seq or r["contestantId"] not in (home, away):
            continue
        t, out = r["typeId"], r["outcome"]
        if t == VAR:  # a goal overturned by VAR no longer counts (an own goal counted for the opponent)
            q = _qualifiers(r)
            if q.get(901) == GOAL_OVERTURNED:
                credited = (r["contestantId"] == home) != (OWN_GOAL in q)
                c((r["periodId"], (60 * r["timeMin"] + r["timeSec"]) // 60), credited)["goalsFor"] -= 1
        if r["x"] is None and t != CARD:
            continue
        cc = c((r["periodId"], (60 * r["timeMin"] + r["timeSec"]) // 60), r["contestantId"] == home)
        x = (r["x"] or 0) * L / 100
        defensive = t in DEFENSIVE or (t == FOUL and out == 0)
        cc["buildPasses"] += t == PASS and x < p["build_line_metres"]
        cc["pressActions"] += defensive and x >= p["press_line_metres"]
        if defensive or t in DEF_EXTRA:
            cc["defActions"] += 1
            cc["defMetres"] += x
        cc["fouls"] += t == FOUL and out == 0
        cc["cards"] += t == CARD
        cc["tackles"] += t == TACKLE
        cc["challenges"] += t == CHALLENGE
        cc["aerials"] += t == AERIAL
        cc["takeOns"] += t == TAKE_ON

    terr, press = defs.get("territory_spell"), defs.get("pressure_spell")
    out, m, lead = [], 0.0, 0
    for key in sorted(comp):
        threat = {}
        for is_home in (True, False):
            cc = comp[key][is_home]
            threat[is_home] = (p["threat_final_third_second"] * cc["finalThirdSeconds"]
                               + p["threat_final_third_entry"] * cc["ftEntries"]
                               + p["threat_box_entry"] * cc["boxEntries"] + p["threat_shot"] * cc["shots"])
        m = p["momentum_alpha"] * (threat[True] - threat[False]) + (1 - p["momentum_alpha"]) * m
        for is_home in (True, False):
            comp[key][is_home]["leadAtStart"] = lead if is_home else -lead
        lead += comp[key][True]["goalsFor"] - comp[key][False]["goalsFor"]
        for is_home in (True, False):
            cc, ball = comp[key][is_home], comp[key][is_home]["ballSeconds"]
            att, fin = (cc["attHalfSeconds"] + 1) / (ball + 2), (cc["finalThirdSeconds"] + 1) / (ball + 2)
            out.append({**cc, "periodId": key[0], "minute": key[1], "minuteLabel": minute_label(*key),
                        "contestantId": home if is_home else away, "isHome": is_home,
                        "attHalfShare": att, "finalThirdShare": fin,
                        "defHeight": cc["defMetres"] / cc["defActions"] if cc["defActions"] else None,
                        "threat": threat[is_home], "momentum": m if is_home else -m,
                        "territoryMinute": bool(terr) and ball >= terr["minBallSeconds"] and att >= terr["minuteAt"],
                        "pressureMinute": bool(press) and ball >= press["minBallSeconds"] and fin >= press["minuteAt"]
                        and cc["ftEntries"] + cc["boxEntries"] + cc["shots"] >= 1})
    return out


def trend_minutes_at_seq(match, events, samples, seq, watermark, defs=None, *, actions, raw, params=None):
    """dbo.trendMinutesAtSeq: minute_rows with the served columns."""
    return [{k: r[k] for k in MINUTE_COLUMNS}
            for r in minute_rows(match, events, samples, seq, watermark, defs, actions=actions, raw=raw,
                                 params=params)]


def _values(s, o, n):
    """Every window indicator of a team from its summed components s, the opponent's o, over n minutes."""
    v = {"possession": _share(s["possessionSeconds"], o["possessionSeconds"]),
         "field_tilt": _share(s["ftActions"], o["ftActions"]),
         "att_half_share": (s["attHalfSeconds"] + 1) / (s["ballSeconds"] + 2),
         "final_third_share": (s["finalThirdSeconds"] + 1) / (s["ballSeconds"] + 2),
         "def_height": s["defMetres"] / s["defActions"] if s["defActions"] else None,
         "box_entries": s["boxEntries"] / n * 5,
         "shots": s["shots"] / n * 5,
         "box_shots": s["boxShots"] / n * 5,
         "ft_entries": s["ftEntries"] / n * 5,
         "fouls": s["fouls"] / n * 5,
         "cards": s["cards"] / n * 5,
         "ppda": (o["buildPasses"] + 1) / (s["pressActions"] + 1),
         "contests": (s["tackles"] + s["challenges"] + s["aerials"] + s["takeOns"]) / n * 5,
         "aggression": (s["fouls"] + 3 * s["cards"] + 0.5 * (s["tackles"] + s["challenges"])) / n * 5,
         "fast_breaks": s["fastBreaks"] / n * 5,
         "directness": (s["forwardMetres"] + 1) / (s["passMetres"] + 2),
         "long_ball_share": (s["longPasses"] + 1) / (s["passes"] + 2),
         "right_flank_share": (s["rightActions"] + 1) / (s["attActions"] + 2),
         "left_flank_share": (s["leftActions"] + 1) / (s["attActions"] + 2)}
    v["dominance"] = 2 * ((v["possession"] + v["field_tilt"] + v["att_half_share"] + _share(s["shots"], o["shots"])
                           + _share(s["ftEntries"], o["ftEntries"])) / 5 - 0.5)
    return v


def _flags(d, window, minutes, value, delta, baseline_minutes):
    level = change = None
    if d["enabled"] and value is not None and minutes >= FULL[window]:
        sign = -1 if d.get("direction") == "low" else 1  # a low-direction trend is notable at or below
        if d["highAt"] is not None and sign * value >= sign * d["highAt"]:
            level = "high"
        elif d["notableAt"] is not None and sign * value >= sign * d["notableAt"]:
            level = "notable"
        if (d["changeAt"] is not None and delta is not None and baseline_minutes >= MIN_BASELINE
                and abs(delta) >= d["changeAt"]):
            change = "rising" if delta > 0 else "falling"
    return level, change


def _windows(rows):
    """Minute keys per window: the current period's last 5, the 10 before them, its last 15, the match before
    those, the current period, the previous period and the whole match."""
    keys = sorted({(r["periodId"], r["minute"]) for r in rows})
    period = keys[-1][0]
    cur = [k for k in keys if k[0] == period]
    last15 = cur[-15:]
    return keys, {"last5": cur[-5:], "prev10": cur[-15:-5], "last15": last15, "pre15": keys[:len(keys) - len(last15)],
                  "prev15": cur[-30:-15], "half": cur, "prevHalf": [k for k in keys if k[0] == period - 1],
                  "match": keys}


def _single(trend_id, d, windows, by, is_home):
    """A SINGLE trend's value: the fade needs a full prev15; game state needs minMinutes in that state."""
    def att(ks):
        return (sum(by[(k, is_home)]["attHalfSeconds"] for k in ks) + 1) / (sum(by[(k, is_home)]["ballSeconds"]
                                                                              for k in ks) + 2)
    if trend_id == "territory_fade":
        return att(windows["prev15"]) - att(windows["last15"]) if len(windows["prev15"]) == 15 else None
    sign = 1 if trend_id == "att_half_leading" else -1
    ks = [k for k in windows["half"] if sign * by[(k, is_home)]["leadAtStart"] > 0]
    return att(ks) if ks and len(ks) >= (d["minMinutes"] or 1) else None


def trends_at_seq(match, events, samples, seq, watermark, defs=None, *, actions, raw, params=None):
    """dbo.trendsAtSeq: indicator × team × window (last5, last15, prev10, half, match), with the baseline
    (last5: prev10; last15: the match before it; half: the previous period), delta and flags; momentum as one
    last5 row per team (now vs the minute before last5)."""
    defs = defs or definitions()
    rows = minute_rows(match, events, samples, seq, watermark, defs, actions=actions, raw=raw, params=params)
    if not rows:
        return []
    keys, windows = _windows(rows)
    by = {((r["periodId"], r["minute"]), r["isHome"]): r for r in rows}
    labels = {k: minute_label(*k) for k in keys}
    values = {}
    for name, ks in windows.items():
        for is_home in (True, False):
            if ks:
                s = {f: sum(by[(k, is_home)][f] for k in ks) for f in COUNTS + SECONDS}
                o = {f: sum(by[(k, not is_home)][f] for k in ks) for f in COUNTS + SECONDS}
                values[(name, is_home)] = _values(s, o, len(ks))
    out = []
    for is_home in (True, False):
        team = match["homeContestantId"] if is_home else match["awayContestantId"]
        for d in sorted(defs, key=lambda d: d["displayOrder"]):
            if d["trendId"] in SINGLE:
                name = SINGLE[d["trendId"]]
                out.append(_row(d, team, name, windows[name], labels, _single(d["trendId"], d, windows, by, is_home),
                                None, None, 0))
            elif d["family"] in ("indicator", "composite"):
                for name in WINDOWS:
                    ks = windows[name]
                    if not ks:
                        continue
                    base = BASELINE.get(name)
                    value = values[(name, is_home)][d["trendId"]]
                    baseline = values[(base, is_home)][d["trendId"]] if base and windows[base] else None
                    delta = value - baseline if value is not None and baseline is not None else None
                    out.append(_row(d, team, name, ks, labels, value, baseline, delta,
                                    len(windows[base]) if base else 0))
            elif d["family"] == "momentum":
                ks, cur = windows["last5"], windows["half"]
                value = by[(ks[-1], is_home)]["momentum"]
                before = cur[-6] if len(cur) >= 6 else None
                baseline = by[(before, is_home)]["momentum"] if before else None
                delta = value - baseline if baseline is not None else None
                out.append(_row(d, team, "last5", ks, labels, value, baseline, delta, len(windows["prev10"])))
    return out


def _row(d, team, window, ks, labels, value, baseline, delta, baseline_minutes):
    level, change = _flags(d, window, len(ks), value, delta, baseline_minutes)
    return {"trendId": d["trendId"], "family": d["family"], "label": d["label"], "meaning": d["meaning"], "unit": d["unit"],
            "contestantId": team, "window": window, "minutes": len(ks), "fromLabel": labels[ks[0]],
            "toLabel": labels[ks[-1]], "value": value, "baseline": baseline, "delta": delta, "level": level,
            "change": change, "flagged": level == "high" or change is not None, "enabled": bool(d["enabled"])}


def spells_at_seq(match, events, samples, seq, watermark, defs=None, *, actions, raw, params=None):
    """dbo.trendSpellsAtSeq: territory and pressure spells, maximal runs of flagged minutes within a period
    that bridge single unflagged minutes, at least minMinutes long; ordered by start, home first. A spell whose
    definition `requires` another kind is enabled only while it overlaps a spell of that kind (same team)."""
    defs = defs or definitions()
    rows = minute_rows(match, events, samples, seq, watermark, defs, actions=actions, raw=raw, params=params)
    keys = sorted({(r["periodId"], r["minute"]) for r in rows})
    by = {((r["periodId"], r["minute"]), r["isHome"]): r for r in rows}
    found = []
    for d in sorted(defs, key=lambda d: d["displayOrder"]):
        if d["family"] != "spell":
            continue
        flag, zone = (("territoryMinute", "attHalfSeconds") if d["trendId"] == "territory_spell"
                      else ("pressureMinute", "finalThirdSeconds"))
        for is_home in (True, False):
            chains, last = [], None
            for i, k in enumerate(keys):
                if not by[(k, is_home)][flag]:
                    continue
                if last is None or keys[last][0] != k[0] or i - last > 2:
                    chains.append([i, i])
                chains[-1][1] = last = i
            for first, end in chains:
                if end - first + 1 < d["minMinutes"]:
                    continue
                span = [by[(k, is_home)] for k in keys[first:end + 1]]
                ball = sum(r["ballSeconds"] for r in span)
                found.append((first, not is_home, d["displayOrder"], {
                    "trendId": d["trendId"], "contestantId": span[0]["contestantId"], "periodId": keys[first][0],
                    "fromLabel": minute_label(*keys[first]), "toLabel": minute_label(*keys[end]),
                    "minutes": end - first + 1, "zoneShare": sum(r[zone] for r in span) / (ball if ball > 1 else 1),
                    "shots": sum(r["shots"] for r in span), "boxEntries": sum(r["boxEntries"] for r in span),
                    "ongoing": end == len(keys) - 1, "enabled": bool(d["enabled"]), "span": (first, end)}))
    for *_, row in found:
        if need := by_id(defs).get(row["trendId"], {}).get("requires"):
            row["enabled"] = row["enabled"] and any(
                o["trendId"] == need and o["contestantId"] == row["contestantId"]
                and o["span"][0] <= row["span"][1] and row["span"][0] <= o["span"][1] for *_, o in found)
    return [{k: v for k, v in row.items() if k != "span"} for *_, row in sorted(found, key=lambda f: f[:3])]


def by_id(defs):
    return {d["trendId"]: d for d in defs}
