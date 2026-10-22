// GENERATED from src/qValue.ts by build.ts. Do not edit; edit the .ts and run `node build.ts`.
// Value of an Opta qualifier, or null when absent or a flag.
function main(qualifiers, qualifierId) {
    var q = (qualifiers || []).filter(function (q) { return q.qualifierId == qualifierId; })[0];
    return q && q.value !== undefined ? String(q.value) : null;
}
