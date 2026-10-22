import type { Branding, Ma1Message } from "./types";

// matchTeams rows from an MA1 message: one per contestant, colours from its branding.
function main(message: Ma1Message) {
    var value = function <T>(v: T | undefined): T | null { return v === undefined ? null : v; };
    return (message.contestant || []).map(function (c) {
        var brand: Branding = (message.branding || {})[c.id as string] || {};
        return {
            matchId: message.matchId, contestantId: c.id, position: c.position, name: value(c.name),
            shortName: value(c.shortName), code: value(c.code),
            knownNames: c.knownNames && c.knownNames.length ? JSON.stringify(c.knownNames) : null,
            primaryColour: value(brand.primaryColour),
            secondaryColour: value(brand.secondaryColour), crestAssetId: value(brand.crestAssetId)
        };
    });
}
