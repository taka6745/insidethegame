// GENERATED from src/matchTeams.ts by build.ts. Do not edit; edit the .ts and run `node build.ts`.
// matchTeams rows from an MA1 message: one per contestant, colours from its branding.
function main(message) {
    var value = function (v) { return v === undefined ? null : v; };
    return (message.contestant || []).map(function (c) {
        var brand = (message.branding || {})[c.id] || {};
        return {
            matchId: message.matchId, contestantId: c.id, position: c.position, name: value(c.name),
            shortName: value(c.shortName), code: value(c.code),
            knownNames: c.knownNames && c.knownNames.length ? JSON.stringify(c.knownNames) : null,
            primaryColour: value(brand.primaryColour),
            secondaryColour: value(brand.secondaryColour), crestAssetId: value(brand.crestAssetId)
        };
    });
}
