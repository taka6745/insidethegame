# Product demonstration

[`product-demo.json`](product-demo.json) is an authored **fictional Chelsea vs Manchester United match**, not footage, a real event feed, a claimed current lineup or a prediction. Team/player names are descriptive references; there is no endorsement.

The 35 deliveries reuse the original synthetic [filter lab](filter-lab.md) sequence, including duplicate/corrected/retracted events. Away-team IDs and player names are changed. Final score: Chelsea 1–0 Manchester United; Bruno has three recorded headed attempts (shots or goals) after corrections.

`POST /product/demo/reset` explicitly selects this recording and starts a new run, without playing it. It refuses while replay is running. A fresh local installation seeds this recording. Existing persisted recordings survive restarts; startup never silently replaces them. `/lab/recording/default` restores the original Chelsea/Madrid filter-lab recording. Changing the recording affects both interfaces because they deliberately share one demo match.

The viewer uses [six authored, bucketed narrative beats](viewer-narratives.md), released only when their supporting events have arrived. Raw event descriptions remain in the developer lab.
