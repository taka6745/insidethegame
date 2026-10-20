# Filter engine: why the index works

This is a general index over the validated structured rule language, not a set of football examples. Player names, event names, minute thresholds and the benchmark recording have no special branches. No runtime model call or generated code is involved.

```text
Event → match + categorical keys → predicate families → clock windows
                                                     ↓
                                  changed totals → sorted result records
```

A rule is a conjunction of typed predicates plus count or sum. A **family** contains rules with identical non-clock predicates, match and aggregation. Family identity uses canonical predicate ordering and membership; it does not attempt to prove every possible logical equivalence.

## Three invariants

1. **The categorical lookup cannot discard a possible match.** Equality/membership conditions form compound keys. Their Cartesian expansion is capped at 64 keys per family; omitted conditions remain in the family predicate and are checked afterwards. Numeric non-clock ranges remain residual predicates. Contradictory categorical intersections index nothing. The event probes each of the 64 masks for the six supported categorical dimensions, then deduplicates the returned families.
2. **The clock lookup returns each matching rule once.** Events have integer seconds in `[0,12000]`. Bounds become exact integer endpoints: `> x → floor(x)+1`, `>= x → ceil(x)`, `< x → ceil(x)-1`, `<= x → floor(x)`. Equality/membership retain only integer points and intersect all constraints. An interval is decomposed into disjoint segment-tree nodes; a point visits its leaf-to-root path. Exactly one node from each containing interval intersects that path. Full-domain rules use the equivalent all-times list. Fractional event clocks are outside the model contract.
3. **Corrections replace contributions.** The latest revision is retained per `(match_id,event_id)`. A newer event contributes `new - previous`, using both old and new index buckets and clock positions. Tombstones contribute zero. Duplicate/older deliveries do nothing; conflicting contents at the current revision raise before changing state. One result version increment occurs for each nonzero net contribution, including when the displayed float happens to round to the previous value.

## Actual costs

Let `N` be registered rules, `H` retained latest event IDs, `D=6` categorical dimensions, `F` candidate families, `P≤16` predicates per rule, `U=16384` tree leaves, `C` clock-matching candidate rules and `K` changed result records. Hash-table operations below use expected amortized costs.

| Operation | Cost / limit |
| --- | --- |
| New-event lookup and update | `O(D·2^D + F·(log U + P) + C + K log K)`; the final term is sorting changed IDs. |
| Correction | The old and new lookup costs, a temporary net-delta map of up to `C_old + C_new` IDs, then `K log K` output sorting. |
| Duplicate/older event | Expected `O(1)` revision lookup; conflicting-current-revision comparison checks a bounded event record. |
| Register one rule | Supplied history first incurs normal ingest costs. Initial total scans retained history: `O(H·P)`. Index insertion adds ≤64 categorical keys for a new family and `O(log U)` interval nodes, or ≤32 integer points. Canonicalization also sorts/hashes the bounded predicate representation. |
| Read one result | Expected `O(1)` dictionary lookup; copying all calculations/rules costs `O(N)`. |
| Storage | Retained events `O(H)`, rules/results `O(N·P)`, ≤64 keys per family, plus interval references `O(N log U)` in the interval case (or ≤32 point references per rule). |

The **64 dictionary probes are not the cost of the entire engine**. A bucket can contain many families; a clock point can match every rule. Residual membership/range predicates can reject candidates after lookup. Sorting and constructing every changed immutable result remain real work: dense demand is at least `Ω(K)` under the current response contract. There is no constant-time promise for 100,000 changing filters, no per-viewer fan-out benchmark, and no benchmark-specific shortcut.

Shared families avoid repeated predicate evaluation, not every accumulator update. A million distinct filters still require storage; registering many filters after a long history still repeats the backfill scan. The engine retains history and has no deletion/eviction API. It is single-process and requires serialized callers; database transactions, recovery and subscriber delivery belong to the application layer. `register(history=...)` can update existing calculations; callers must publish/persist those updates deliberately. It is not an atomic batch transaction.

## Evidence and boundaries

[General differential tests](../tests/test_filter_properties.py) independently interpret plain predicate data with exact rational sums. They cover all 12,001 allowed integer clock values against generated clock conjunctions, and three reproducible randomized streams with categorical membership, non-clock ranges, count/sum, missing fields, two matches, late registration, out-of-order revisions, duplicates, retractions and conflicts. Every stream prefix checks totals, versions, changed IDs and ordering; shuffled history checks final convergence. They do not call the production predicate evaluator to derive expected values.

The [100 handwritten cases and performance runs](../benchmarks/README.md) provide additional evidence, including the [measured optimization comparison](../benchmarks/results/optimization.md). Tests establish behavior for their covered inputs, not a production capacity guarantee.

**Numeric contract issue found during this audit:** `distance_metres` accepts any finite float between 0 and 200, while Decimal accumulation uses the default 28-digit precision. Adding `1e-27`, adding `100`, then retracting `100` yields a live zero although backfill of the remaining event yields `1e-27`. This is not an indexing failure, but the current broad numeric input contract does not justify universal order-independent sum claims. The accepted measurement precision or the accumulator representation needs an explicit resolution; ordinary football-scale fixture sums do not exercise this extreme.

**Hackathon conclusion:** keep this general index and avoid further speculative optimization for rare cases. It removes repeated predicate work; it cannot eliminate all required updates. If a target workload demands more capacity, measure registration/backfill separately from ingestion and measure actual output cardinality before changing the design. The linked timings are prior measurements; this audit adds correctness coverage and complexity analysis, not a new performance run.
