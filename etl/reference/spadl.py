# SPADL conversion rules ported from socceraction 1.5.3 (spadl/config.py, spadl/base.py, spadl/opta.py
# and data/opta parsers), https://github.com/ML-KULeuven/socceraction.
# Copyright (c) 2019 KU Leuven Machine Learning Research Group. MIT License; see THIRD-PARTY-NOTICES.txt.
"""MA3 rows -> SPADL actions, in pure Python (no pandas), for whole matches and for a live prefix.

Same rules and float arithmetic as socceraction's MA3JSONParser -> OptaLoader.events -> opta.convert_to_actions
(tests/test_spadl.py compares every recording with it). Deliberate differences, none of which changes any
recording's output:
- Input is one match's MA3 rows in MA3 seq order, which the feed sends in clock order; socceraction's
  (period, minute, second, timestamp) sort is the identity on such input and is not repeated.
- Look-ahead never crosses a segment: a period, cut after its first period_end (Opta type 30). socceraction's
  pandas shifts read across periods; bounding them lets period_end finalise every action of the period.
- A shot row (types 13-16) is final on arrival: the deflected-pass rule (a following successful ball touch
  moves the end location) is not applied to shots.
- Where socceraction would produce NaN at the end of its input (a trailing ball recovery or deflection with
  nothing after it), the location is kept.
- Missing x/y (period start and end rows) read as 0, as real MA3 sends them.

Live finalisation: every action carries `finalSeq`, the canonical seq after which none of its values (or its
actionId) can change. A shot is final at its own seq; other actions at the next one or two rows (the next
action or the deflection check); period_end finalises the rest of the period. Snapshot s may read actions with
finalSeq <= s, and incremental conversion equals whole-match conversion (tests/test_spadl.py).
"""
import math

FIELD_LENGTH, FIELD_WIDTH = 105.0, 68.0
BODYPARTS = ["foot", "head", "other", "head/other", "foot_left", "foot_right"]
RESULTS = ["fail", "success", "offside", "owngoal", "yellow_card", "red_card"]
ACTIONTYPES = ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short",
               "take_on", "foul", "tackle", "interception", "shot", "shot_penalty", "shot_freekick", "keeper_save",
               "keeper_claim", "keeper_punch", "keeper_pick_up", "clearance", "bad_touch", "non_action", "dribble",
               "goalkick"]
MIN_DRIBBLE_LENGTH, MAX_DRIBBLE_LENGTH, MAX_DRIBBLE_DURATION = 3.0, 60.0, 10.0
# Seconds socceraction subtracts per period to get time_seconds (period-relative clock).
PERIOD_OFFSET = {1: 0, 2: 2700, 3: 5400, 4: 6300, 5: 7200}

# Opta MA3 types the rules read (socceraction's names in comments).
PASS, OFFSIDE_PASS, TAKE_ON, FOUL, TACKLE, INTERCEPTION = 1, 2, 3, 4, 7, 8
SAVE, CLAIM, CLEARANCE, MISS, POST, ATTEMPT_SAVED, GOAL = 10, 11, 12, 13, 14, 15, 16
END, DELETED, PUNCH, BALL_RECOVERY, KEEPER_PICK_UP, BALL_TOUCH, BLOCKED_PASS = 30, 43, 41, 49, 52, 61, 74
SHOT_EVENTS = {MISS, POST, ATTEMPT_SAVED, GOAL}
KEEPER_EVENTS = {SAVE, CLAIM, PUNCH, KEEPER_PICK_UP}
NON_ACTION = ACTIONTYPES.index("non_action")

# Team-relative zones (the acting team attacks towards x = 105): thirds, with each penalty area split out.
ZONES = ["own_box", "defensive_third", "middle_third", "final_third", "opp_box"]
BOX_DEPTH, BOX_HALF_WIDTH = 16.5, 20.16
PASS_FAMILY = ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short",
               "goalkick"]
SHOT_FAMILY = ["shot", "shot_penalty", "shot_freekick"]

COLUMNS = ["actionId", "originalEventId", "periodId", "timeSeconds", "teamId", "playerId", "startX", "startY",
           "endX", "endY", "typeId", "typeName", "resultId", "resultName", "bodypartId", "bodypartName",
           "seq", "finalSeq", "sourceEventId", "sourceTypeId", "clockSeconds", "videoSeconds", "possessionId",
           "bodypartObserved", "startZone", "endZone", "fromShotOffTarget", "defensiveBlock"]
FROM_SHOT_OFF_TARGET, DEFENSIVE_BLOCK = 190, 94  # Opta qualifiers that tell a save apart


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scale(value, length):
    return min(max(value, 0.0), 100.0) / 100 * length


def _end(q, axis):
    """socceraction's _get_end_x / _get_end_y: pass end, blocked-shot location, or the goal line."""
    own, blocked = (140, 146) if axis == "x" else (141, 147)
    if own in q:
        return _float(q[own])
    if blocked in q:
        return _float(q[blocked])
    if 102 in q:
        return 100.0 if axis == "x" else _float(q[102])
    return None


def _type(t, outcome, q):
    if 238 in q:  # fair play
        return "non_action"
    if t in (PASS, OFFSIDE_PASS):
        cross, freekick, corner = 2 in q, 5 in q, 6 in q
        if 107 in q:
            return "throw_in"
        if freekick and (cross or 1 in q or 155 in q):
            return "freekick_crossed"
        if freekick:
            return "freekick_short"
        if corner and cross:
            return "corner_crossed"
        if corner:
            return "corner_short"
        if cross:
            return "cross"
        return "goalkick" if 124 in q else "pass"
    if t in SHOT_EVENTS:
        return "shot_penalty" if 9 in q else "shot_freekick" if 26 in q else "shot"
    return {TAKE_ON: "take_on", TACKLE: "tackle", INTERCEPTION: "interception", BLOCKED_PASS: "interception",
            SAVE: "keeper_save", CLAIM: "keeper_claim", PUNCH: "keeper_punch", KEEPER_PICK_UP: "keeper_pick_up",
            CLEARANCE: "clearance"}.get(t, "foul" if t == FOUL and not outcome else
                                         "bad_touch" if t == BALL_TOUCH and not outcome else "non_action")


def _result(t, outcome, q):
    if t == OFFSIDE_PASS:
        return "offside"
    if t in (FOUL, MISS, POST, ATTEMPT_SAVED, BALL_TOUCH):
        return "fail"
    if t == GOAL:
        return "owngoal" if 28 in q else "success"
    return "success" if outcome else "fail"


def _bodypart(t, q):
    """(bodypart, observed): observed when a qualifier names it rather than the default."""
    for ids, part in (((15, 3, 168), "head"), ((21,), "other"), ((20,), "foot_right"), ((72,), "foot_left"),
                      ((107,), "other")):
        if any(i in q for i in ids):
            return part, True
    return ("other" if t in KEEPER_EVENTS else "foot"), False


def zone(x, y, team_id, home_team_id):
    """Team-relative zone of a SPADL location (SPADL's frame has the home team attacking towards x = 105)."""
    rx = x if team_id == home_team_id else FIELD_LENGTH - x
    in_band = abs(y - FIELD_WIDTH / 2) <= BOX_HALF_WIDTH
    if rx >= FIELD_LENGTH - BOX_DEPTH and in_band:
        return "opp_box"
    if rx <= BOX_DEPTH and in_band:
        return "own_box"
    return "defensive_third" if rx < FIELD_LENGTH / 3 else "middle_third" if rx < 2 * FIELD_LENGTH / 3 else "final_third"


def _row(m):
    """One MA3 row as the converter reads it (OptaLoader.events + the per-row part of convert_to_actions)."""
    q = {int(x["qualifierId"]): x.get("value") for x in m.get("qualifier") or []}
    t, outcome = int(m["typeId"]), bool(int(m.get("outcome", 1)))
    x, y = _float(m.get("x")) or 0.0, _float(m.get("y")) or 0.0
    ex, ey = _end(q, "x"), _end(q, "y")
    period, second = int(m["periodId"]), max(int(m["timeSec"]), 0)
    time_seconds = float(60 * int(m["timeMin"]) + second - PERIOD_OFFSET.get(period, 0))
    part, observed = _bodypart(t, q)
    return {"m": m, "t": t, "outcome": outcome, "q": q, "period": period, "time": time_seconds,
            "team": m["contestantId"], "player": m.get("playerId"), "seq": int(m["eventSeq"]),
            "sx": _scale(x, FIELD_LENGTH), "sy": _scale(y, FIELD_WIDTH),
            "ex": _scale(ex if ex is not None else x, FIELD_LENGTH), "ey": _scale(ey if ey is not None else y, FIELD_WIDTH),
            "type": _type(t, outcome, q), "result": _result(t, outcome, q), "body": part, "observed": observed}


def _segments(rows, closed):
    """Split at period changes and after each period's first period_end. Yields (rows, closer seq or None)."""
    start, ended = 0, set()
    for i, r in enumerate(rows):
        boundary = i + 1 == len(rows) or rows[i + 1]["period"] != r["period"]
        if r["t"] == END and r["period"] not in ended:
            ended.add(r["period"])
            boundary = True
        if boundary:
            seg = rows[start:i + 1]
            if r["t"] == END or (i + 1 == len(rows) and closed):
                closer = r["seq"]
            elif i + 1 < len(rows):
                closer = rows[i + 1]["seq"]
            else:
                closer = None  # open: look-ahead past the end is still unknown
            yield seg, closer
            start = i + 1


INF = math.inf


def _convert_segment(seg, closer, home):
    """SPADL actions of one segment, each with `dep`: the last row index (len(seg) = the closer, INF =
    unknown yet) whose content its values or its existence depend on."""
    n = len(seg)
    off = n if closer is not None else INF  # reading past the end
    rows = [dict(r) for r in seg]

    def next_index(i, keep):
        return next((j for j in range(i + 1, n) if keep(j)), None)

    # Ball recoveries -> dribble to the next action's start, or dropped (_fix_recoveries).
    keep_dep = list(range(n))
    for i, r in enumerate(rows):
        if r["t"] != BALL_RECOVERY:
            continue
        j = next_index(i, lambda k: seg[k]["type"] != "non_action")
        if j is None:
            nx, ny, keep_dep[i] = r["ex"], r["ey"], off
        else:
            nx, ny, keep_dep[i] = seg[j]["sx"], seg[j]["sy"], j
        same = abs(r["ex"] - nx) < MIN_DRIBBLE_LENGTH and abs(r["ey"] - ny) < MIN_DRIBBLE_LENGTH
        r["type"], r["ex"], r["ey"] = ("non_action" if same else "dribble"), nx, ny
    deps = list(keep_dep)

    # Deflected passes: a following successful ball touch moves the end to two rows on
    # (_fix_unintentional_ball_touches); not applied to shots, which are final on arrival.
    for i, r in enumerate(rows):
        if r["t"] in SHOT_EVENTS:
            continue
        if i + 1 >= n:
            deps[i] = max(deps[i], off)
            continue
        deps[i] = max(deps[i], i + 1)
        touch = seg[i + 1]
        if touch["t"] == BALL_TOUCH and touch["outcome"]:
            if i + 2 >= n:
                deps[i] = max(deps[i], off)
                continue
            deps[i] = max(deps[i], i + 2)
            after = seg[i + 2]
            r["ex"], r["ey"] = after["sx"], after["sy"]
            if r["type"] == "pass" and r["team"] == after["team"]:
                r["result"] = "success"

    kept = [i for i in range(n) if rows[i]["type"] != "non_action"]
    for i in kept:
        r = rows[i]
        if r["result"] == "owngoal" and r["type"] == "shot":  # _fix_owngoals
            r["ex"], r["ey"], r["type"] = FIELD_LENGTH - r["ex"], FIELD_WIDTH - r["ey"], "bad_touch"
        if r["team"] != home:  # _fix_direction_of_play
            r["sx"], r["ex"] = FIELD_LENGTH - r["sx"], FIELD_LENGTH - r["ex"]
            r["sy"], r["ey"] = FIELD_WIDTH - r["sy"], FIELD_WIDTH - r["ey"]

    # The next action and what it took to know it (every row between, including recoveries' look-ahead).
    nxt = {}
    for p, i in enumerate(kept):
        j = kept[p + 1] if p + 1 < len(kept) else None
        span = range(i + 1, (j if j is not None else n - 1) + 1)
        dep = max((keep_dep[k] for k in span), default=i)
        nxt[i] = (j, dep if j is not None else max(dep, off))
    for i in kept:
        r, (j, dep) = rows[i], nxt[i]
        if r["type"] == "clearance":  # _fix_clearances: end at the next action's start (own start if last)
            r["ex"], r["ey"] = (rows[j]["sx"], rows[j]["sy"]) if j is not None else (r["sx"], r["sy"])
            deps[i] = max(deps[i], dep)
        elif r["type"] == "interception":  # _fix_interceptions
            if j is None or rows[j]["team"] != r["team"]:
                r["result"] = "fail"
            deps[i] = max(deps[i], dep)

    out = []
    for p, i in enumerate(kept):
        a = rows[i]
        a["dep"] = deps[i] if p == 0 else max(deps[i], nxt[kept[p - 1]][1])
        out.append(a)
        j = nxt[i][0]
        if j is None:
            continue
        b = rows[j]  # _add_dribbles
        dx, dy = a["ex"] - b["sx"], a["ey"] - b["sy"]
        if (a["team"] == b["team"] and b["type"] != "foul" and b["type"] != "shot" and b["body"] != "head"
                and MIN_DRIBBLE_LENGTH ** 2 <= dx ** 2 + dy ** 2 <= MAX_DRIBBLE_LENGTH ** 2
                and b["time"] - a["time"] < MAX_DRIBBLE_DURATION and a["period"] == b["period"]):
            out.append({"m": None, "next": b, "prev": a, "period": b["period"], "time": (a["time"] + b["time"]) / 2,
                        "team": b["team"], "player": b["player"], "seq": b["seq"], "sx": a["ex"], "sy": a["ey"],
                        "ex": b["sx"], "ey": b["sy"], "type": "dribble", "result": "success", "body": "foot",
                        "observed": False, "dep": nxt[i][1]})
    seqs = [r["seq"] for r in seg] + [closer]
    for a in out:
        a["depSeq"] = None if a["dep"] == INF else seqs[a["dep"]]
    return out


def convert(messages, home_team_id, closed=True, first_action_id=0, first_final_seq=0):
    """SPADL actions (dicts with COLUMNS) for MA3 rows of one match in MA3 seq order.

    closed: the input is the whole match (look-ahead past the end reads as "nothing follows"). Otherwise the
    input is a live prefix: rows ending in an open segment may be returned with finalSeq None (pending), and
    only a prefix of the result is final. A tail restart starts at a stored action's row and passes that
    action's actionId and finalSeq."""
    rows = [_row(m) for m in messages if int(m["typeId"]) != DELETED]
    out, final, action_id = [], first_final_seq, first_action_id
    for seg, closer in _segments(rows, closed):
        for a in _convert_segment(seg, closer, home_team_id):
            final = None if final is None or a["depSeq"] is None else max(final, a["seq"], a["depSeq"])
            out.append(_columns(a, action_id, final, home_team_id))
            action_id += 1
    return out


def _columns(a, action_id, final, home):
    m = a["m"]
    if m is None:  # inserted dribble: between the previous and the next action
        prev, nxt = a["prev"]["m"], a["next"]["m"]
        video = (None if prev.get("videoSeconds") is None or nxt.get("videoSeconds") is None
                 else (prev["videoSeconds"] + nxt["videoSeconds"]) / 2)
        source, possession = {"originalEventId": None, "sourceEventId": None, "sourceTypeId": None}, nxt.get("possessionId")
    else:
        video, possession = m.get("videoSeconds"), m.get("possessionId")
        source = {"originalEventId": int(m["id"]), "sourceEventId": m.get("sourceEventId"), "sourceTypeId": int(m["typeId"])}
    return {"actionId": action_id, "originalEventId": source["originalEventId"], "periodId": a["period"],
            "timeSeconds": a["time"], "teamId": a["team"], "playerId": a["player"],
            "startX": a["sx"], "startY": a["sy"], "endX": a["ex"], "endY": a["ey"],
            "typeId": ACTIONTYPES.index(a["type"]), "typeName": a["type"],
            "resultId": RESULTS.index(a["result"]), "resultName": a["result"],
            "bodypartId": BODYPARTS.index(a["body"]), "bodypartName": a["body"],
            "seq": a["seq"], "finalSeq": final, "sourceEventId": source["sourceEventId"],
            "sourceTypeId": source["sourceTypeId"], "clockSeconds": PERIOD_OFFSET.get(a["period"], 0) + a["time"],
            "videoSeconds": video, "possessionId": possession, "bodypartObserved": a["observed"],
            "startZone": zone(a["sx"], a["sy"], a["team"], home), "endZone": zone(a["ex"], a["ey"], a["team"], home),
            "fromShotOffTarget": m is not None and FROM_SHOT_OFF_TARGET in a["q"],
            "defensiveBlock": m is not None and DEFENSIVE_BLOCK in a["q"]}


def actions(messages, home_team_id):
    """Whole-match conversion: every action, all final."""
    return convert(messages, home_team_id, closed=True)


def final_actions(messages, home_team_id, first_action_id=0, first_final_seq=0):
    """The final prefix of a live conversion (the rows a snapshot at the input's last seq may read)."""
    out = convert(messages, home_team_id, closed=False, first_action_id=first_action_id, first_final_seq=first_final_seq)
    return out[:next((i for i, a in enumerate(out) if a["finalSeq"] is None), len(out))]
