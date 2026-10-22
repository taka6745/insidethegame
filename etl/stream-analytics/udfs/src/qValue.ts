import type { Qualifier } from "./types";

// Value of an Opta qualifier, or null when absent or a flag.
function main(qualifiers: Qualifier[] | null | undefined, qualifierId: number): string | null {
    var q = (qualifiers || []).filter(function (q) { return q.qualifierId == qualifierId; })[0];
    return q && q.value !== undefined ? String(q.value) : null;
}
