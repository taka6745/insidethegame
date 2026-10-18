"""Generate a synthetic Opta MA1/MA3-style match for ETL development.

SYNTHETIC DATA: invented teams, players and events, labelled `synthetic: true`.
Temporary until data-generation/ supplies matches.

The scripted moments cover every key event: goal, missed penalty, VAR goal
overturn, second-yellow red card, scored penalty and own goal. Final score 1-2.

    python -m seeder.generate --seed 7 --out seeder/matches/itg-syn-0001.jsonl
"""
import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from etltools import opta

NOMINAL_KICKOFF = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
HALF_TIME_BREAK = timedelta(minutes=15)
ADDED_MINUTES = {1: 2, 2: 4}

TEAMS = {
    "home": {"id": "c-riv", "name": "Riverside FC", "shortName": "Riverside", "code": "RIV"},
    "away": {"id": "c-har", "name": "Harbour Athletic", "shortName": "Harbour", "code": "HAR"},
}
SURNAMES = {
    "home": ["Okafor", "Lindqvist", "Moreau", "Tanaka", "Byrne", "Costa", "Novak", "Haddad",
             "Mensah", "Reyes", "Kowalski", "Doyle", "Iwu", "Santos"],
    "away": ["Park", "Ferreira", "Walsh", "Nkemelu", "Bauer", "Quinn", "Ortega", "Sato",
             "Adeyemi", "Larsen", "Petit", "Murphy", "Rossi", "Kaur"],
}
POSITIONS = ["GK", "DF", "DF", "DF", "DF", "MF", "MF", "MF", "FW", "FW", "MF", "DF", "MF", "FW"]


def opponent(side):
    return "away" if side == "home" else "home"


def clamp(v, lo=0.5, hi=99.5):
    return max(lo, min(hi, v))


class MatchBuilder:
    def __init__(self, match_id, seed):
        self.match_id = match_id
        self.rng = random.Random(seed)
        self.seed = seed
        self.players = {
            side: [{"playerId": f"p-{TEAMS[side]['code'].lower()}-{n:02d}", "name": SURNAMES[side][n - 1],
                    "shirtNumber": n, "position": POSITIONS[n - 1], "starter": n <= 11} for n in range(1, 15)]
            for side in TEAMS
        }
        self.on_pitch = {side: [p for p in self.players[side] if p["starter"]] for side in TEAMS}
        self.booked = set()
        self.events = []
        self.team_seq = {"home": 0, "away": 0}
        self.period, self.clock = 1, 0.0
        self.period_wall_start = {1: NOMINAL_KICKOFF}
        self.script = sorted(self.scripted_moments())

    def player(self, side, shirt):
        return next(p for p in self.players[side] if p["shirtNumber"] == shirt)

    def pick(self, side, exclude=None):
        outfield = [p for p in self.on_pitch[side] if p["position"] != "GK" and p is not exclude]
        return self.rng.choice(outfield)

    def keeper(self, side):
        return self.player(side, 1)

    def emit(self, side, type_id, player=None, outcome=1, x=None, y=None, qualifiers=(), dt=0.0):
        self.clock += dt
        self.team_seq[side] += 1
        total = int(self.clock)
        base_min = opta.PERIOD_START_MIN[self.period]
        wall = self.period_wall_start[self.period] + timedelta(seconds=self.clock - base_min * 60)
        event = {
            "feed": "MA3", "schemaVersion": 1, "matchId": self.match_id, "synthetic": True,
            "seq": len(self.events) + 1, "id": 2_700_000_000 + len(self.events) + 1,
            "eventId": self.team_seq[side], "typeId": type_id, "periodId": self.period,
            "timeMin": total // 60, "timeSec": total % 60, "contestantId": TEAMS[side]["id"],
            "playerId": player["playerId"] if player else None, "playerName": player["name"] if player else None,
            "outcome": outcome,
            "x": None if x is None else round(x, 1), "y": None if y is None else round(y, 1),
            "timeStamp": wall.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "qualifier": [{"qualifierId": q} if v is None else {"qualifierId": q, "value": str(v)} for q, v in qualifiers],
        }
        self.events.append(event)
        return event

    def pass_(self, side, player, x, y, nx, ny, complete=True, extra=(), dt=None):
        quals = [*extra, (opta.Q_END_X, round(nx, 1)), (opta.Q_END_Y, round(ny, 1))]
        if nx > 85 and (y < 20 or y > 80):
            quals.append((opta.Q_CROSS, None))
        return self.emit(side, opta.PASS, player, int(complete), x, y, quals,
                         dt=self.rng.uniform(2, 5) if dt is None else dt)

    def kick_off(self, side, dt=0.0):
        taker = self.pick(side)
        self.pass_(side, taker, 50, 50, 38, self.rng.uniform(30, 70), extra=[(opta.Q_KICK_OFF, None)], dt=dt)
        return side, 38.0

    # ---- open play -------------------------------------------------------

    def possession(self, side, x):
        rng = self.rng
        y = rng.uniform(10, 90)
        player = self.pick(side)
        while True:
            if x > 78 and rng.random() < 0.2:
                return self.shot(side, player, x, y)
            if rng.random() < 0.035:
                return self.foul_on(side, x, y)
            complete = rng.random() < (0.87 if x < 60 else 0.72)
            nx, ny = clamp(x + rng.uniform(-8, 16)), clamp(y + rng.uniform(-25, 25))
            receiver = self.pick(side, exclude=player)
            self.pass_(side, player, x, y, nx, ny, complete)
            if not complete:
                other, ox, oy = opponent(side), 100 - nx, 100 - ny
                kind = opta.CLEARANCE if ox < 20 else rng.choice([opta.INTERCEPTION, opta.TACKLE, opta.BALL_RECOVERY])
                self.emit(other, kind, self.pick(other), 1, ox, oy, dt=rng.uniform(1, 3))
                return other, ox
            player, x, y = receiver, nx, ny

    def shot(self, side, player, x, y):
        rng, other = self.rng, opponent(side)
        r = rng.random()
        if r < 0.4:
            self.emit(side, opta.MISS, player, 0, x, y, dt=rng.uniform(1, 3))
            gk = self.keeper(other)
            self.pass_(other, gk, 6, 50, rng.uniform(35, 60), rng.uniform(20, 80),
                       complete=rng.random() < 0.6, extra=[(opta.Q_GOAL_KICK, None)], dt=rng.uniform(15, 30))
            return other, 45.0
        if r < 0.6:
            self.emit(side, opta.ATTEMPT_SAVED, player, 0, x, y, [(opta.Q_BLOCKED, None)], dt=rng.uniform(1, 3))
            self.emit(other, opta.BALL_RECOVERY, self.pick(other), 1, 100 - x + 5, 100 - y, dt=rng.uniform(1, 2))
            return other, 100 - x + 5
        if r < 0.95:
            self.emit(side, opta.ATTEMPT_SAVED, player, 0, x, y, dt=rng.uniform(1, 3))
            self.emit(other, opta.SAVE, self.keeper(other), 1, 100 - x, 100 - y)
            if rng.random() < 0.5:
                return self.corner(side)
            return other, 8.0
        self.emit(side, opta.POST, player, 0, x, y, dt=rng.uniform(1, 3))
        self.emit(other, opta.CLEARANCE, self.pick(other), 1, 8, 50, dt=rng.uniform(1, 2))
        return other, 15.0

    def corner(self, side):
        rng, cy = self.rng, self.rng.choice([0.5, 99.5])
        self.emit(side, opta.CORNER_AWARDED, None, 1, 99.5, cy, dt=rng.uniform(1, 2))
        complete = rng.random() < 0.35
        self.pass_(side, self.pick(side), 99.5, cy, 92, rng.uniform(35, 65), complete,
                   extra=[(opta.Q_CORNER, None)], dt=rng.uniform(20, 35))
        if complete:
            return side, 90.0
        other = opponent(side)
        self.emit(other, opta.CLEARANCE, self.pick(other), 1, 8, 50, dt=rng.uniform(1, 2))
        return other, 25.0

    def foul(self, offender_side, offender, x, y, penalty=False, card=None, dt=None):
        """Opta records a foul as a pair: offender (outcome 0) and fouled player (outcome 1)."""
        rng, fouled_side = self.rng, opponent(offender_side)
        quals = [(opta.Q_PENALTY, None)] if penalty else []
        self.emit(offender_side, opta.FOUL, offender, 0, 100 - x, 100 - y, quals,
                  dt=rng.uniform(1, 3) if dt is None else dt)
        self.emit(fouled_side, opta.FOUL, self.pick(fouled_side), 1, x, y, quals)
        if card:
            self.emit(offender_side, opta.CARD, offender, 1, 100 - x, 100 - y, [(card, None)], dt=rng.uniform(20, 40))
            if card == opta.Q_YELLOW:
                self.booked.add(offender["playerId"])
            else:
                self.on_pitch[offender_side].remove(offender)

    def foul_on(self, side, x, y):
        rng, other = self.rng, opponent(side)
        offender = self.pick(other)
        unbooked = offender["playerId"] not in self.booked and offender["shirtNumber"] != 4
        self.foul(other, offender, x, y, card=opta.Q_YELLOW if unbooked and rng.random() < 0.12 else None)
        nx = clamp(x + rng.uniform(5, 25))
        self.pass_(side, self.pick(side), x, y, nx, rng.uniform(15, 85), rng.random() < 0.8,
                   extra=[(opta.Q_FREE_KICK, None)], dt=rng.uniform(10, 25))
        return side, nx

    # ---- scripted key moments ------------------------------------------

    def scripted_moments(self):
        return [
            (22 * 60 + 40, self.goal, "home"),
            (29 * 60 + 50, self.booking, "home"),
            (37 * 60 + 10, self.penalty_missed, "home"),
            (52 * 60 + 5, self.goal_overturned, "away"),
            (60 * 60 + 30, self.second_yellow, "home"),
            (64 * 60 + 0, self.substitution, "away"),
            (69 * 60 + 20, self.penalty_goal, "away"),
            (76 * 60 + 0, self.substitution, "home"),
            (83 * 60 + 40, self.own_goal, "home"),
        ]

    def build_up(self, side, to_x=86):
        x, y, player = 55.0, self.rng.uniform(30, 70), self.pick(side)
        while x < to_x:
            nx, ny = min(to_x, x + self.rng.uniform(8, 14)), clamp(y + self.rng.uniform(-15, 15), 20, 80)
            receiver = self.player(side, 9) if nx >= to_x else self.pick(side, exclude=player)
            self.pass_(side, player, x, y, nx, ny)
            player, x, y = receiver, nx, ny
        return player, x, y

    def goal(self, side):
        scorer, x, y = self.build_up(side)
        self.emit(side, opta.GOAL, scorer, 1, x + 2, y, dt=self.rng.uniform(1, 2))
        return self.kick_off(opponent(side), dt=self.rng.uniform(50, 70))

    def booking(self, side):
        offender = self.player(side, 4)
        self.foul(side, offender, 60, 40, card=opta.Q_YELLOW)
        return opponent(side), 60.0

    def penalty_missed(self, side):
        other = opponent(side)
        _, x, y = self.build_up(side, to_x=88)
        self.foul(other, self.player(other, 5), x, y, penalty=True)
        taker = self.player(side, 9)
        self.emit(side, opta.ATTEMPT_SAVED, taker, 0, 88.5, 50, [(opta.Q_PENALTY, None)], dt=self.rng.uniform(60, 90))
        self.emit(other, opta.SAVE, self.keeper(other), 1, 11.5, 50, [(opta.Q_PENALTY, None)])
        return other, 8.0

    def goal_overturned(self, side):
        scorer, x, y = self.build_up(side)
        goal = self.emit(side, opta.GOAL, scorer, 1, x + 2, y, dt=self.rng.uniform(1, 2))
        self.emit(side, opta.VAR_DECISION, scorer, 1, None, None,
                  [(opta.Q_RELATED_EVENT, goal["eventId"]), (opta.Q_VAR_OUTCOME, "goal-overturned")], dt=70)
        other = opponent(side)
        self.pass_(other, self.pick(other), 15, y, 45, 50, extra=[(opta.Q_FREE_KICK, None)], dt=20)
        return other, 45.0

    def second_yellow(self, side):
        self.foul(side, self.player(side, 4), 55, 60, card=opta.Q_SECOND_YELLOW)
        return opponent(side), 55.0

    def substitution(self, side):
        for off_shirt, on_shirt in ((7, 12), (11, 13)):
            off, on = self.player(side, off_shirt), self.player(side, on_shirt)
            self.emit(side, opta.PLAYER_OFF, off, 1, dt=self.rng.uniform(5, 15))
            self.emit(side, opta.PLAYER_ON, on, 1)
            self.on_pitch[side][self.on_pitch[side].index(off)] = on
        return side, 40.0

    def penalty_goal(self, side):
        other = opponent(side)
        _, x, y = self.build_up(side, to_x=88)
        self.foul(other, self.player(other, 3), x, y, penalty=True)
        self.emit(side, opta.GOAL, self.player(side, 9), 1, 88.5, 50, [(opta.Q_PENALTY, None)],
                  dt=self.rng.uniform(60, 90))
        return self.kick_off(other, dt=self.rng.uniform(50, 70))

    def own_goal(self, side):
        attacker = opponent(side)
        self.build_up(attacker, to_x=88)
        self.emit(side, opta.GOAL, self.player(side, 5), 1, 4, 52, [(opta.Q_OWN_GOAL, None)], dt=self.rng.uniform(1, 2))
        return self.kick_off(side, dt=self.rng.uniform(50, 70))

    # ---- match ---------------------------------------------------------

    def play_period(self, period, kicking_side):
        self.period = period
        self.clock = opta.PERIOD_START_MIN[period] * 60.0
        for side in TEAMS:
            self.emit(side, opta.START)
        side, x = self.kick_off(kicking_side)
        end = (opta.PERIOD_END_MIN[period] + ADDED_MINUTES[period]) * 60
        while self.clock < end:
            if self.script and self.script[0][0] <= self.clock:
                _, moment, moment_side = self.script.pop(0)
                side, x = moment(moment_side)
            else:
                side, x = self.possession(side, x)
        self.clock = max(self.clock, end) + self.rng.uniform(1, 20)
        for side in TEAMS:
            self.emit(side, opta.END)

    def build(self):
        self.play_period(1, "home")
        p1_wall_end = datetime.fromisoformat(self.events[-1]["timeStamp"].replace("Z", "+00:00"))
        self.period_wall_start[2] = p1_wall_end + HALF_TIME_BREAK
        self.play_period(2, "away")
        assert not self.script, f"unplayed scripted moments: {self.script}"
        return [self.match_info(), *self.events]

    def match_info(self):
        return {
            "feed": "MA1", "schemaVersion": 1, "matchId": self.match_id, "synthetic": True,
            "description": f"{TEAMS['home']['name']} v {TEAMS['away']['name']} (synthetic)",
            "scheduledKickoff": NOMINAL_KICKOFF.isoformat().replace("+00:00", "Z"),
            "timeStamp": (NOMINAL_KICKOFF - timedelta(hours=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "provenance": f"SYNTHETIC: generated by etl/seeder/generate.py (seed={self.seed}). Not real match data.",
            "contestant": [{**TEAMS[side], "position": side, "lineup": self.players[side]} for side in TEAMS],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--match-id", default="itg-syn-0001")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "matches" / "itg-syn-0001.jsonl")
    args = parser.parse_args()
    messages = MatchBuilder(args.match_id, args.seed).build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(m, separators=(",", ":")) + "\n" for m in messages), encoding="utf-8")
    print(f"wrote {len(messages)} messages to {args.out}")


if __name__ == "__main__":
    main()
