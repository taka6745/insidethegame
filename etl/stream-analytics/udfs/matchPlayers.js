// matchPlayers rows from an MA1 message: every contestant's lineup.
function main(message) {
    var value = function (v) { return v === undefined ? null : v; };
    var rows = [];
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
