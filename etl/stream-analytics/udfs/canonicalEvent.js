// canonicalEvents row from a MatchEvent v2 message (reference/pipeline.py canonical_row).
function main(message) {
    var e = message.event || {};
    var value = function (v) { return v === undefined ? null : v; };
    return {
        matchId: message.matchId, seq: message.seq, eventId: e.event_id,
        revision: e.revision === undefined ? 1 : e.revision, eventType: e.event_type,
        teamId: value(e.team_id), playerId: value(e.player_id), bodyPart: value(e.body_part),
        periodId: e.period === undefined ? 1 : e.period, matchTimeSeconds: e.match_time_seconds,
        outcome: value(e.outcome), distanceMetres: value(e.distance_metres), deleted: e.deleted ? 1 : 0,
        videoSeconds: value(e.video_seconds), x: value(e.x), y: value(e.y), possessionId: value(e.possession_id),
        qualifiers: JSON.stringify(e.qualifiers || {}), eventTime: message.timeStamp
    };
}
