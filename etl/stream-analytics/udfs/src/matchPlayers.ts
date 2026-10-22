import type { Ma1Message } from "./types";

// matchPlayers rows from an MA1 message: every contestant's lineup.
function main(message: Ma1Message) {
    var value = function <T>(v: T | undefined): T | null { return v === undefined ? null : v; };
    var rows: MatchPlayerRow[] = [];
    (message.contestant || []).forEach(function (c) {
        (c.lineup || []).forEach(function (p) {
            rows.push({
                matchId: message.matchId, playerId: p.playerId, contestantId: c.id, name: value(p.name),
                shirtNumber: value(p.shirtNumber), position: value(p.position),
                starter: p.starter === undefined || p.starter === null ? null : (p.starter ? 1 : 0)
            });
        });
    });
    return rows;
}

interface MatchPlayerRow {
    matchId?: string; playerId?: string; contestantId?: string; name: string | null;
    shirtNumber: number | null; position: string | null; starter: number | null;
}
