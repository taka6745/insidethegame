# Bucketed narratives arrive from the narrative engine

![Correct service boundary](narrative-framing.svg)

| Narrative engine owns | User backend owns |
| --- | --- |
| Neutral match analysis and source narratives | Viewer profiles and match preferences |
| Audience layers, options and semantic descriptions | Selecting the viewer's bucket |
| Framing for every available DB bucket | Routing supplied text unchanged |
| Persisting/publishing bucket versions and history | Live delivery and history retrieval |

**Current implementation:** `/dev/narratives` and the optional Service Bus adapter receive already-bucketed messages using `backend.domain.Narrative`. The original 12 combinations are supported by this harness. The backend does not invoke a framing model or expose audience-authoring endpoints. GraphQL history remains upstream-owned.

Set `NARRATIVE_SERVICEBUS_CONNECTION_STRING` in the ignored backend environment file to consume topic `narratives`, subscription `user-backend`. The local default uses fake upstream HTTP notifications. Message validation precedes delivery; completion follows routing. Invalid payloads are dead-lettered and transient upstream errors are retried. This single-process harness is not a production multi-replica delivery system.

**Preserved for the narrative engine:** the [framing prototype](../../narrative-engine/prototypes/bucket_framing/README.md), its flexible audience models and 12-combination seed. That prototype still needs integration with narrative-owned storage and the author workflow. Its real-model wording/latency evaluation did not pass demo readiness.

The mistakenly added backend framing runtime, endpoints and startup configuration have been removed. Existing development tables are untouched but unused. The implementation is recoverable in Git commit `882aa2e`.

Run `./dev up backend` for API tests and the existing end-to-end bucket-routing smoke check. No neutral-to-bucket model work is performed by this backend.

Verified locally: 292 backend tests, Docker replay/filter-lab smoke checks, and an actual Service Bus emulator message delivered unchanged to the matching viewer WebSocket.
