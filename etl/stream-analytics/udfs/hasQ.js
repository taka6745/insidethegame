// GENERATED from src/hasQ.ts by build.ts. Do not edit; edit the .ts and run `node build.ts`.
// 1 if the Opta qualifier list contains qualifierId, else 0.
function main(qualifiers, qualifierId) {
    return (qualifiers || []).some(function (q) { return q.qualifierId == qualifierId; }) ? 1 : 0;
}
