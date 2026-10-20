"""Compact, readable prompt text for match info, events, statistics and the key-event ledger.

Inputs are the ETL shapes: the MA1 payload from `matches`, MA3 payloads from `rawEvents`,
`matchStatsAsOfs` rows and `keyEvents` rows. Codes follow etl/contracts/opta-codes.json.
Passes are counted per team rather than listed, which keeps a minute to a few lines.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from narrative_engine.core.models import MatchClock

PERIOD_NAMES = {1: "first half", 2: "second half", 3: "extra time, first half", 4: "extra time, second half"}

Q_CROSS, Q_CORNER_TAKEN, Q_PENALTY, Q_OWN_GOAL = 2, 6, 9, 28
Q_YELLOW, Q_SECOND_YELLOW, Q_RED, Q_BLOCKED, Q_VAR_OUTCOME = 31, 32, 33, 82, 901

SIMPLE_EVENTS = {
    6: "corner awarded", 7: "tackle", 8: "interception", 12: "clearance", 13: "shot off target",
    14: "shot hits the post", 18: "substituted off", 19: "substituted on", 49: "ball recovery",
}


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    code: str
    position: str


@dataclass
class MatchInfo:
    matchId: str
    home: Team
    away: Team
    synthetic: bool
    players: dict = field(default_factory=dict)  # playerId -> name

    @classmethod
    def from_ma1(cls, ma1):
        teams = {c["position"]: Team(c["id"], c["name"], c.get("code") or c["name"][:3].upper(), c["position"])
                 for c in ma1["contestant"]}
        players = {p["playerId"]: p["name"] for c in ma1["contestant"] for p in c.get("lineup", [])}
        return cls(ma1["matchId"], teams["home"], teams["away"], bool(ma1.get("synthetic")), players)

    def team(self, contestant_id):
        return self.home if contestant_id == self.home.id else self.away

    def opponent(self, contestant_id):
        return self.away if contestant_id == self.home.id else self.home

    def player(self, player_id, fallback=None):
        return self.players.get(player_id) or fallback or "unknown player"


def has_q(event, qualifier_id):
    return any(q["qualifierId"] == qualifier_id for q in event.get("qualifier", []))


def q_value(event, qualifier_id):
    return next((q.get("value") for q in event.get("qualifier", []) if q["qualifierId"] == qualifier_id), None)


def describe(event):
    """What happened in one MA3 event, or None if it is not worth a line of its own."""
    t, ok = event["typeId"], event["outcome"] == 1
    penalty = has_q(event, Q_PENALTY)
    if t == 1:
        if has_q(event, Q_CORNER_TAKEN):
            return f"corner taken, {'found a teammate' if ok else 'cleared'}"
        if has_q(event, Q_CROSS):
            return f"cross, {'completed' if ok else 'not completed'}"
        return None
    if t == 4:
        if ok:
            return "won a penalty" if penalty else None
        return "foul, penalty conceded" if penalty else "foul"
    if t == 10:
        return "penalty save" if penalty else "save"
    if t == 15:
        if penalty:
            return "penalty saved"
        return "shot blocked" if has_q(event, Q_BLOCKED) else "shot saved"
    if t in (13, 14) and penalty:
        return "penalty missed"
    if t == 16:
        if has_q(event, Q_OWN_GOAL):
            return "OWN GOAL"
        return "GOAL (penalty)" if penalty else "GOAL"
    if t == 17:
        if has_q(event, Q_SECOND_YELLOW):
            return "second yellow card, sent off"
        return "red card, sent off" if has_q(event, Q_RED) else "yellow card"
    if t == 900:
        return f"VAR decision: {q_value(event, Q_VAR_OUTCOME) or 'review'}"
    return SIMPLE_EVENTS.get(t)


def render_events(events, info):
    """Events grouped under a heading per match minute, with a pass count per team."""
    if not events:
        return "No recorded events."
    minutes = defaultdict(list)
    for e in sorted(events, key=lambda e: (e["periodId"], e["timeMin"], e["timeSec"], e.get("seq", 0))):
        minutes[MatchClock(e["periodId"], e["timeMin"])].append(e)
    lines = []
    for clock, items in minutes.items():
        lines.append(f"{clock.label} ({PERIOD_NAMES.get(clock.periodId, f'period {clock.periodId}')})")
        passes = defaultdict(lambda: [0, 0])
        periods_seen = set()
        for e in items:
            if e["typeId"] in (30, 32):
                if (e["typeId"], e["periodId"]) not in periods_seen:
                    periods_seen.add((e["typeId"], e["periodId"]))
                    lines.append(f"  {e['timeMin']:02d}:{e['timeSec']:02d} {PERIOD_NAMES.get(e['periodId'], 'period')} "
                                 f"{'kicks off' if e['typeId'] == 32 else 'ends'}")
                continue
            team = info.team(e["contestantId"])
            if e["typeId"] == 1:
                passes[team.code][0] += 1
                passes[team.code][1] += e["outcome"]
            text = describe(e)
            if text:
                who = f" {info.player(e['playerId'], e.get('playerName'))}" if e.get("playerId") else ""
                lines.append(f"  {e['timeMin']:02d}:{e['timeSec']:02d} {team.code}{who}: {text}")
        if passes:
            counts = ", ".join(f"{code} {done}/{total} completed" for code, (total, done) in sorted(passes.items()))
            lines.append(f"  passes: {counts}")
    return "\n".join(lines)


STAT_LINES = (
    ("Possession (share of passes)", lambda r: f"{r['possessionPct']}%" if r.get("possessionPct") is not None else "n/a"),
    ("Shots (on target)", lambda r: f"{r['shots']} ({r['shotsOnTarget']})"),
    ("Passes (completed)", lambda r: f"{r['passes']} ({r['passesCompleted']})"),
    ("Corners", lambda r: r["corners"]),
    ("Fouls", lambda r: r["fouls"]),
    ("Yellow cards", lambda r: r["yellowCards"]),
    ("Red cards", lambda r: r["redCards"]),
)


def render_stats(rows, info):
    """Two matchStatsAsOfs rows (home and away) as a small table."""
    if not rows:
        return "No statistics yet."
    by_position = {r["position"]: r for r in rows}
    home, away = by_position.get("home"), by_position.get("away")
    if not home or not away:
        return "No statistics yet."
    lines = [
        f"As of {home['minuteLabel']} ({PERIOD_NAMES.get(home['periodId'], '')})",
        f"Score: {info.home.name} (home) {home['goals']} - {away['goals']} {info.away.name} (away)",
        f"| Statistic | {info.home.name} | {info.away.name} |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {name} | {value(home)} | {value(away)} |" for name, value in STAT_LINES]
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
    for r in ordered:
        clock = MatchClock(r["periodId"], r["timeMin"])
        note = " [later overturned by VAR]" if r["id"] in overturned else ""
        lines.append(f"- {clock.label} {r['timeMin']:02d}:{r['timeSec']:02d}: {describe_key_event(r, info)}{note}")
    return "\n".join(lines)


def render_match(info):
    label = " Synthetic match data." if info.synthetic else ""
    return (f"Home team: {info.home.name} ({info.home.code}). "
            f"Away team: {info.away.name} ({info.away.code}).{label}")
