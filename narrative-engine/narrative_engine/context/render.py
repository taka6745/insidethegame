"""Compact, readable prompt text for match info, play, statistics and the key-event ledger.

Inputs are the ETL shapes: the MA1 payload from `matches`, `spadlActions` rows (SPADL actions,
etl/README.md Contracts Output 3), MA3 payloads from `rawEvents` for the facts SPADL leaves out
(period start and end, yellow cards, substitutions), `keyEvents` rows (goals, red cards,
penalties, VAR) and `executeStatsAtSeq` rows (the SPADL stat catalogue, local/README.md Contracts §4).
Action types and results keep their SPADL names. Passes and carries are counted per team rather
than listed, which keeps a minute to a few lines.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from narrative_engine.core.models import MatchClock

PERIOD_NAMES = {1: "first half", 2: "second half", 3: "extra time, first half", 4: "extra time, second half"}

ACTION_FIELDS = ("actionId periodId teamId playerId typeName resultName bodypartName bodypartObserved "
                 "startY endY startZone endZone seq finalSeq clockSeconds fromShotOffTarget defensiveBlock")
PASS_FAMILY = {"pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed", "corner_short",
               "goalkick"}
COUNTED = {"pass", "throw_in", "goalkick", "dribble"}  # counted per team, listed only when offside or an own goal
WIDTH = 68.0
ZONE_RANK = {"own_box": 0, "defensive_third": 1, "middle_third": 2, "final_third": 3, "opp_box": 4}
BODYPARTS = {"foot_left": "left foot", "foot_right": "right foot"}

Q_SECOND_YELLOW, Q_RED = 32, 33
FACT_TYPES = {17, 18, 19}  # MA3 rows outside SPADL and keyEvents: yellow cards, substitutions (and period start/end)


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    code: str
    position: str
    other_names: tuple = ()  # MA1 shortName and knownNames ("Forgeham", "the Forgemen"): accepted in authored text

    @property
    def names(self):
        return (self.name, self.code, *self.other_names)


@dataclass
class MatchInfo:
    matchId: str
    home: Team
    away: Team
    synthetic: bool
    players: dict = field(default_factory=dict)  # playerId -> name
    periods: int = None    # MA1 capabilities.periods: the final period, whose end finishes the match
    timeStamp: str = None  # when the feed sent the MA1 (purge-all cut-off)

    @classmethod
    def from_ma1(cls, ma1):
        teams = {c["position"]: Team(c["id"], c["name"], c.get("code") or c["name"][:3].upper(), c["position"],
                                     tuple(n for n in dict.fromkeys([c.get("shortName"), *(c.get("knownNames") or [])])
                                           if isinstance(n, str) and n.strip() and n != c["name"]))
                 for c in ma1["contestant"]}
        players = {p["playerId"]: p["name"] for c in ma1["contestant"] for p in c.get("lineup", [])}
        periods = (ma1.get("capabilities") or {}).get("periods")
        return cls(ma1["matchId"], teams["home"], teams["away"], bool(ma1.get("synthetic")), players,
                   int(periods) if periods else None, ma1.get("timeStamp"))

    def team(self, contestant_id):
        return self.home if contestant_id == self.home.id else self.away

    def opponent(self, contestant_id):
        return self.away if contestant_id == self.home.id else self.home

    def player(self, player_id, fallback=None):
        return self.players.get(player_id) or fallback or "unknown player"


def has_q(event, qualifier_id):
    return any(q["qualifierId"] == qualifier_id for q in event.get("qualifier", []))


def place(zone, y, attacking_home):
    """Where on the pitch, from the acting team's view (SPADL frame: home attacks towards x = 105,
    y = 0 is its right touchline)."""
    if zone == "opp_box":
        return "box"
    if zone == "own_box":
        return "own box"
    if zone == "defensive_third":
        return "own third"
    rel = y if attacking_home else WIDTH - y
    side = "right" if rel < WIDTH / 3 else "left" if rel > 2 * WIDTH / 3 else None
    if zone == "final_third":
        return f"{side} wing" if side else "final third"
    return f"{side} midfield" if side else "midfield"


def describe_action(a, info):
    """One SPADL action: type, result, body part (when observed) and where it went."""
    parts = [a["typeName"], a["resultName"]]
    # SPADL makes every Opta save a keeper_save; ETL flags the ones that are not goalkeeper saves.
    if a.get("defensiveBlock"):
        parts.append("outfield block, not a goalkeeper save")
    elif a.get("fromShotOffTarget"):
        parts.append("touch of a shot going wide, not a save")
    if a.get("bodypartObserved"):
        parts.append(BODYPARTS.get(a["bodypartName"], a["bodypartName"]))
    home = a["teamId"] == info.home.id
    start = place(a["startZone"], a["startY"], home)
    end = place(a["endZone"], a["endY"], home)
    parts.append(f"{start} → {end}" if a["typeName"] in PASS_FAMILY | {"clearance"} and end != start else start)
    return ", ".join(parts)


def listed(a):
    return a["typeName"] not in COUNTED or a["resultName"] in ("offside", "owngoal")


def entered(a, zone):
    """A successful pass-family action or carry into `zone` (as the catalogue's entries count it)."""
    return (a["resultName"] == "success" and (a["typeName"] in PASS_FAMILY or a["typeName"] == "dribble")
            and ZONE_RANK[a["startZone"]] < ZONE_RANK[zone] <= ZONE_RANK[a["endZone"]])


def describe_fact(event):
    t = event["typeId"]
    if t == 17:
        if has_q(event, Q_SECOND_YELLOW) or has_q(event, Q_RED):
            return None  # a key event
        return "yellow card"
    return {18: "substituted off", 19: "substituted on"}.get(t)


def totals(actions, info):
    """Per team: pass-family completion, carries, and entries into the final third and the box."""
    by_team = defaultdict(list)
    for a in actions:
        by_team[a["teamId"]].append(a)
    lines = []
    for team in (info.home, info.away):
        rows = by_team.get(team.id)
        if not rows:
            continue
        passes = [a for a in rows if a["typeName"] in PASS_FAMILY]
        parts = [f"passes {sum(a['resultName'] == 'success' for a in passes)}/{len(passes)} completed"]
        if carries := sum(a["typeName"] == "dribble" for a in rows):
            parts.append(f"carries {carries}")
        for zone, name in (("final_third", "final-third entries"), ("opp_box", "box entries")):
            if n := sum(entered(a, zone) for a in rows):
                parts.append(f"{name} {n}")
        lines.append(f"{team.code} {', '.join(parts)}")
    return "; ".join(lines)


def render_events(info, actions, events=(), keys=(), start=None):
    """Play under a heading per match minute: SPADL actions (passes and carries counted per team),
    MA3 facts outside SPADL, and key events. Each line is `mm:ss TEAM Player: what`. Actions from
    before minute `start` (settled only in this window) go under its heading."""
    entries = []  # (period, second, order within the second, text or None, action or None)
    for a in actions:
        second = int(a["clockSeconds"])
        text = None
        if listed(a):
            who = f" {info.player(a['playerId'])}" if a.get("playerId") else ""
            text = f"{info.team(a['teamId']).code}{who}: {describe_action(a, info)}"
        entries.append((a["periodId"], second, 1, text, a))
    periods_seen = set()
    for e in events:
        second = e["timeMin"] * 60 + e["timeSec"]
        if e["typeId"] in (30, 32):
            if (e["typeId"], e["periodId"]) not in periods_seen:
                periods_seen.add((e["typeId"], e["periodId"]))
                what = "kicks off" if e["typeId"] == 32 else "ends"
                entries.append((e["periodId"], second, 0 if e["typeId"] == 32 else 3,
                                f"{PERIOD_NAMES.get(e['periodId'], 'period')} {what}", None))
        elif e["typeId"] in FACT_TYPES and (text := describe_fact(e)):
            who = f" {info.player(e['playerId'], e.get('playerName'))}" if e.get("playerId") else ""
            entries.append((e["periodId"], second, 2, f"{info.team(e['contestantId']).code}{who}: {text}", None))
    for k in keys:
        entries.append((k["periodId"], k["timeMin"] * 60 + k["timeSec"], 2,
                        f"key event: {describe_key_event(k, info)}", None))
    if not entries:
        return "No recorded events."
    minutes = defaultdict(list)
    for entry in sorted(entries, key=lambda x: x[:3]):
        minutes[max(MatchClock(entry[0], entry[1] // 60), start or MatchClock(0, 0))].append(entry)
    lines = []
    for clock, items in sorted(minutes.items()):
        lines.append(f"{clock.label} ({PERIOD_NAMES.get(clock.periodId, f'period {clock.periodId}')})")
        lines += [f"  {s // 60:02d}:{s % 60:02d} {text}" for _, s, _, text, _ in items if text]
        if counts := totals([a for *_, a in items if a], info):
            lines.append(f"  totals: {counts}")
    return "\n".join(lines)


def score(keys, info):
    """Goals per team from keyEvents rows: goals, own goals for the opponent, minus VAR overturns."""
    goals = {info.home.id: 0, info.away.id: 0}
    for k in keys:
        team, other = k["contestantId"], info.opponent(k["contestantId"]).id
        if k["keyType"] == "Goal":
            goals[team] += 1
        elif k["keyType"] == "OwnGoal":
            goals[other] += 1
        elif k["keyType"] == "VarOverturn":
            goals[other if k.get("detail") == "own-goal-overturned" else team] -= 1
    return goals


STAT_LINES = (  # (label, catalogue kind, kind shown in brackets)
    ("Possession (share of ball time)", "possession", None),
    ("Shots (on target)", "shots", "shots_on_target"),
    ("Passes (completed)", "passes", "passes_completed"),
    ("Crosses (completed)", "crosses", "crosses_completed"),
    ("Final-third entries", "final_third_entries", None),
    ("Box entries", "box_entries", None),
    ("Corners", "corners", None),
    ("Fouls", "fouls", None),
    ("Cards", "cards", None),
)


def render_stats(rows, info, clock, keys=()):
    """executeStatsAtSeq rows as a small table, with the score from the key events up to `clock`."""
    if not rows:
        return "No statistics yet."
    by = {(r["kind"], r["contestantId"]): r for r in rows}

    def value(kind, team):
        r = by.get((kind, team.id))
        if not r or not r["available"] or r["value"] is None:
            return "n/a"
        v = r["value"]
        return f"{round(v, 1):g}{r['unit']}" if isinstance(v, float) else f"{v}{r['unit']}"

    def cell(kind, extra, team):
        return f"{value(kind, team)} ({value(extra, team)})" if extra else value(kind, team)

    goals = score(keys, info)
    lines = [
        f"As of {clock.label} ({PERIOD_NAMES.get(clock.periodId, '')})",
        f"Score: {info.home.name} (home) {goals[info.home.id]} - {goals[info.away.id]} {info.away.name} (away)",
        f"| Statistic | {info.home.name} | {info.away.name} |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {name} | {cell(k, x, info.home)} | {cell(k, x, info.away)} |" for name, k, x in STAT_LINES]
    # The catalogue's own definitions, so counts that are not nested (box vs final-third entries) are read as served.
    meanings = [(name, next((r.get("definition") for r in rows if r["kind"] == k and r.get("definition")), None))
                for name, k, _ in STAT_LINES]
    if any(text for _, text in meanings):
        lines += ["What each counts:", *(f"- {name}: {text}" for name, text in meanings if text)]
    return "\n".join(lines)


def describe_key_event(row, info):
    team = info.team(row["contestantId"])
    player = info.player(row.get("playerId"))
    kind, detail = row["keyType"], row.get("detail")
    if kind == "Goal":
        return f"Goal for {team.name}, {player}{' (penalty)' if detail == 'penalty' else ''}"
    if kind == "OwnGoal":
        return f"Own goal by {player} ({team.name}), counts for {info.opponent(row['contestantId']).name}"
    if kind == "PenaltyAwarded":
        return f"Penalty to {info.opponent(row['contestantId']).name}, conceded by {player} ({team.name})"
    if kind == "PenaltyMissed":
        return f"Penalty missed by {player} ({team.name})"
    if kind == "RedCard":
        return f"Red card for {player} ({team.name}){', second yellow' if detail == 'second-yellow' else ''}"
    if kind == "VarOverturn":
        what = "own goal" if detail == "own-goal-overturned" else "goal"
        return f"VAR overturns the {team.name} {what} ({player})"
    return f"{kind} ({team.name})"


def render_ledger(rows, info, overturned=frozenset()):
    """The key-event ledger in match order. `overturned` holds keyEvents ids cancelled by VAR."""
    if not rows:
        return "No key events yet."
    ordered = sorted(rows, key=lambda r: (r["periodId"], r["timeMin"], r["timeSec"]))
    lines = []
    for i, r in enumerate(ordered):
        clock = MatchClock(r["periodId"], r["timeMin"])
        note = " [later overturned by VAR]" if r["id"] in overturned else ""
        if r["keyType"] in ("Goal", "OwnGoal", "VarOverturn"):  # the score after it, so a reader need not count
            goals = score(ordered[:i + 1], info)
            note += f" (score now {info.home.name} {goals[info.home.id]}-{goals[info.away.id]} {info.away.name})"
        lines.append(f"- {clock.label} {r['timeMin']:02d}:{r['timeSec']:02d}: {describe_key_event(r, info)}{note}")
    return "\n".join(lines)


def render_match(info):
    label = " Synthetic match data." if info.synthetic else ""
    return (f"Home team: {info.home.name} ({info.home.code}). "
            f"Away team: {info.away.name} ({info.away.code}).{label}")


WINDOWS = {"last5": "last 5 minutes", "last15": "last 15 minutes", "half": "this half", "match": "whole match"}
# (prev10, the 10 minutes before last5, is served as last5's baseline and shown as its "from" value)


def number(value):
    """Trend values as the prompts show them (and the analyst must quote them)."""
    if value is None:
        return "n/a"
    return f"{value:.2f}" if abs(value) < 10 else f"{value:.1f}"


UNITS = {"m": "m", "per 5 min": "/5min"}  # shares, indices and ratios have none


def trend_note(row):
    notes = [row["level"]] if row.get("level") else []
    if row.get("trend") and row.get("previous") is not None:
        notes.append(f"{row['trend']} from {number(row['previous'])}")
    return f" ({', '.join(notes)})" if notes else ""


def render_trends(rows, info, flagged_only=False, always=()):
    """ETL trend rows (local/README.md Contracts §4b) per window and team: `label value (level, rising from previous)`,
    then what each label measures (the definitions' plain-words `meaning`). `flagged_only` keeps rows with a level
    or trend, plus the whole-match `always` indicators (the policy's `author_match_indicators`), so the author sees
    the shape of the game without every number."""
    if not rows:
        return "No trend data yet."
    keep = [r for r in rows if r["window"] in WINDOWS and (not flagged_only or r.get("level") or r.get("trend")
                                                          or (r["window"] == "match" and r["indicator"] in always))]
    lines = []
    for window, label in WINDOWS.items():
        for team in (info.home, info.away):
            items = [r for r in keep if r["window"] == window and r["contestantId"] == team.id]
            if items:
                text = "; ".join(f"{name(r)} {number(r['value'])}{UNITS.get(r.get('unit'), '')}{trend_note(r)}"
                                 for r in items)
                lines.append(f"[{window}: {label}] {team.name} ({team.code}): {text}")
    if not lines:
        return "Nothing notable in the trends."
    return "\n".join(lines + ["What each measures:", *meanings(keep, name)])


def name(row):
    return row.get("label") or row["indicator"]


def meanings(rows, key):
    """One `- key: meaning` line per trend shown, in order (rows without a meaning, like the ledger's goals, none)."""
    seen = {}
    for r in rows:
        if r.get("meaning"):
            seen.setdefault(key(r), r["meaning"])
    return [f"- {k}: {m}" for k, m in seen.items()]


def render_trend_table(rows, info):
    """The analyst's trend table: per window, one line per indicator with both teams side by side, in the
    exact fields an evidence item cites (`window`, the indicator's label, team code, value as shown). Labels are
    plain words, so the analyst never sees an id it could copy into fan-facing text; the validator maps them back."""
    if not rows:
        return "No trend data yet."
    lines = [f"Teams: {info.home.code} = {info.home.name} (home), {info.away.code} = {info.away.name} (away)."]
    for window, label in WINDOWS.items():
        items = [r for r in rows if r["window"] == window]
        if not items:
            continue
        lines.append(f'window "{window}" ({label}):')
        for indicator in dict.fromkeys(name(r) for r in items):
            by_team = {r["contestantId"]: r for r in items if name(r) == indicator}
            cells = [f"{t.code} {number(r['value'])}{UNITS.get(r.get('unit'), '')}{trend_note(r)}"
                     for t in (info.home, info.away) if (r := by_team.get(t.id))]
            lines.append(f"  {indicator}: {' | '.join(cells)}")
    if legend := meanings([r for r in rows if r["window"] in WINDOWS], name):
        lines += ["What each indicator measures:", *legend]
    return "\n".join(lines)


def render_spells(spells, info):
    """Trend spells: runs of minutes one team held territory or pressure."""
    if not spells:
        return "No spells."
    out = []
    for s in spells:
        ongoing = ", still going" if s.get("ongoing") else ""
        out.append(f"- {info.team(s['contestantId']).name} {s['kind']} spell {s['fromLabel']}-{s['toLabel']} "
                   f"({s['minutes']} min{ongoing})")
    return "\n".join(out)


def render_storylines(lines, info, ledger=(), focus=None, ids=True, *, beats):
    """Open and resolved storylines with their latest `beats` beats and linked key events. `focus` marks the one this
    step must advance; `ids` (the analyst) shows the ids it uses for storyline moves, on open storylines only (a
    resolved one takes no more moves)."""
    if not lines:
        return "No storylines yet."
    keys = {r["id"]: r for r in ledger}
    order = {"active": 0, "dormant": 1, "resolved": 2}
    out = []
    for s in sorted(lines, key=lambda s: (s["id"] != focus, order[s["status"]], -s["salience"], s["n"])):
        mark = "FOCUS " if s["id"] == focus else ""
        named = ids and s["status"] != "resolved"
        name = f"{s['id']} [{s['label']}] " if named else ""
        state = s["status"] + (f": {s['outcome']}" if s["status"] == "resolved" and s.get("outcome") else "")
        title = "" if named else f"\"{s['label']}\" "
        out.append(f"- {mark}{name}{title}({state}; since {s['openedAt']['label']})")
        out += [f"    {b['at']['label']} {b['headline']}" + (f" ({b['explanation']})" if b.get("explanation") else "")
                for b in s["beats"][-beats:]]
        if linked := [keys[k] for k in s["keyEventIds"] if k in keys]:
            out.append("    linked key events: " + "; ".join(
                f"{MatchClock(r['periodId'], r['timeMin']).label} {describe_key_event(r, info)}" for r in linked))
    return "\n".join(out)
