import type { Qualifier } from "./types";

// 1 if the Opta qualifier list contains qualifierId, else 0.
function main(qualifiers: Qualifier[] | null | undefined, qualifierId: number): number {
    return (qualifiers || []).some(function (q) { return q.qualifierId == qualifierId; }) ? 1 : 0;
}
