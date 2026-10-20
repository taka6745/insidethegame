# Shared predicate and clock-window optimization

Measured 18 October 2026 on the same development Mac, Python 3.12.12. Each row registers **100,000 unique rules** and runs the unchanged GRF workload with the same fixed-seed spread order and 10-second replay budget. No model, database, network or viewer delivery is timed.

```text
match event → compound family lookup → clock-window index
                                    → shared predicate evaluation → changed results
```

| Workload | Before p95 | After p95 | Mean capacity before → after | Peak RSS before → after |
| --- | ---: | ---: | ---: | ---: |
| Selective | 6.164 ms | 3.674 ms | 184 → 376 events/s | 462 → 512 MiB |
| Overlapping | 594.192 ms | 242.459 ms | 2.1 → 7.4 events/s | 329 → 338 MiB |

The engine groups rules with identical non-clock predicates and aggregation. It probes an integer-clock segment tree, then evaluates each remaining family's shared predicate once. These workloads each measured **1 predicate-family evaluation and 15 time-index probes per new event**. Future/expired windows are excluded before calculation updates. There is no event-history rescan per input event.

**Result delivery still costs work.** Every changed rule gets its own immutable result and version, in the same sorted order as before. If 100,000 rules actually change, the engine still constructs 100,000 results. This is a matching optimization, not constant-time fan-out. Unique predicate families, membership expansion and broad matching demand still need capacity limits.

In the service-time queue model, the overlapping sample now averages **67% utilization at 5 events/s**; it still cannot sustain 100/s. Selective averages 27% at 100/s. These are modeled rates, not end-to-end service guarantees.

**Limits:** before/after sample counts are 1,841/3,771 selective and 21/75 overlapping because runs are time bounded. The seed/order is identical, but faster runs observe a longer sample. This is single-run development-host evidence, not a controlled statistical capacity study. GC/scheduler spikes remain; added indexing also increases memory. No claim is made for 1m–100m registered filters or viewer connections.

Verified: **58 engine/time-index tests**, **100/100 handcrafted gold cases**, and **100 generated rules across all 14,018 GRF events** against independent reference totals. Tests cover strict/fractional clock bounds, memberships, empty intersections, corrections, retractions, duplicate deliveries, count/sum, version stability and late backfill.

[Before raw results](optimization-before.json) · [After raw results](optimization-after.json). Raw reports include source and recording hashes. Existing earlier results remain preserved.

```sh
PYTHONPATH=user-backend python -m benchmarks.performance \
  --sizes 100000 --event-order spread --replay-timeout 10 \
  --suite-timeout 100 --output .local/benchmarks/optimized-comparison
```
