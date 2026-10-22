import type { Contestant, Json, Ma1Message } from "./types";

// matches row from an MA1 message: home/away contestants picked by position.
function main(message: Ma1Message) {
    var copy: Json = {};
    for (var key in message) {
        if (["EventProcessedUtcTime", "PartitionId", "EventEnqueuedUtcTime"].indexOf(key) < 0) copy[key] = message[key];
    }
    var side = function (position: string): Contestant {
        return (message.contestant || []).filter(function (c) { return c.position === position; })[0] || {};
    };
    return {
        matchId: message.matchId,
        description: message.description || null,
        homeContestantId: side("home").id, homeName: side("home").name || null,
        awayContestantId: side("away").id, awayName: side("away").name || null,
        scheduledKickoff: message.scheduledKickoff,
        synthetic: message.synthetic ? 1 : 0,
        payload: JSON.stringify(copy),
        fixture: message.fixture || null, sourceMatchId: message.sourceMatchId || null, runId: message.runId || null,
        capabilities: message.capabilities ? JSON.stringify(message.capabilities) : null
    };
}
