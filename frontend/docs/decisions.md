# Decisions

> **In short:** plain TypeScript modules without a bundler, one push connection per viewer, all statistics and narratives from upstream services, and a fictional league with original artwork. Production delivery needs a CDN and a managed push gateway.

| | |
| --- | --- |
| **Design references** | [design/references.md](design/references.md) |
| **Production gaps** | [terraform decisions §2](../../terraform/docs/decisions.md#2-before-a-production-release) |

## 1. Choices

*In short: small, cacheable and honest.*

| Choice | Why |
| --- | --- |
| No bundler or framework; `tsc` output plus one content fingerprint | Fewer moving parts; relative imports stay inside one cached version |
| `hls.js` light build served from the same origin | Strict CSP: no CDN, no workers |
| One WebSocket for state, HTTP for actions | No per-viewer polling or model loop; reconnect restores an authoritative snapshot |
| Data held until the picture reaches it | Cards and narratives never run ahead of the footage |
| Questions carry the shown `seq` | Answers never cite events the viewer has not seen |
| Viewer-safe error sentences in `match/`, backend messages in `lab/` and `dev/` | Viewers never see exceptions; developers need the detail |
| Fictional Elephant League, original crests and wordmark, CSS sting | No third-party marks; only the Microsoft logo for the Agent Framework credit ([provenance](../assets/league/PROVENANCE.md)) |
| Agent Framework credit, not "powered by Copilot" | Truthful attribution |

## 2. Production boundary

*In short: what the demo deployment does not cover.*

- Static assets can move behind Azure Front Door or a CDN; the socket transport would be replaced by an authenticated delivery gateway or an Azure Web PubSub adapter using Microsoft's supported recovery SDK (not deployed).
- Multiple backend replicas still need shared session ownership, durable delivery and coordinated match calculations.
- Profiles are demo identities, not authentication.
- Limits bound browser and server work; no viewer-capacity number has been measured.

## 3. Open items

*In short: small, known gaps.*

- The UI ships unminified (no bundler); the [benchmark](components/benchmarks.md) budget allows for it.
- Per-viewer rewind of live footage is not built.
