# Context and trigger rules

Design notes transcribed from the [original board](../legacy/design/plan.excalidraw), with the agreed service interfaces. No runtime exists yet.

## Shared memory

1. Summarise each completed minute using its events and current statistics.
2. At 11 minute summaries, compress the oldest five into one five-minute block.
3. At four five-minute blocks, merge the oldest two with the existing earlier-match block, if present.
4. Record each block's time interval and mark replaced blocks with `supersededBy`.

The context builder reads non-superseded blocks in chronological order. The intended steady-state bound is one earlier-match block, up to three five-minute blocks and six to ten recent minute summaries; the opening minutes naturally contain fewer. Coverage must have no gaps or overlaps.

The author also receives raw events since the last summary, the key-event ledger, current statistics and the last N narratives for its audience bucket. N remains to be selected.

## Key events and triggers

The upstream ledger preserves goals, red cards, penalties and VAR overturns with exact timestamps. It is authoritative if summaries disagree; compression must not become the sole record of these events.

| Trigger | Planned work |
| --- | --- |
| `MinuteClosed` | Summarise, then compress if due. |
| `KeyEventDetected` | Debounce nearby events, then author for every available DB bucket. |
| Ten match minutes since the last narrative step | Author for every available DB bucket. |
| Half time | Finish compression; optionally author a half-time narrative. |

No minute summaries run during half time. Match time includes period, minute and added minute. Debounce duration and exact event/message schemas remain implementation details.

## Storage and delivery

Cosmos DB holds `contextBlocks` (coverage, summary, supersession and statistics timestamp), `narratives` (bucket, sequence, trigger and text) and `matches` (clock and checkpoints).

Persist narratives before publishing their Service Bus notification. Serve history through this service's GraphQL interface. Consumers use stable narrative IDs and sequence numbers to reconnect reliably; narrative deduplication belongs here rather than in the user backend.

The three example prompt files remain unchanged. The board requests structured JSON for agent outputs, while the author prompt requests text only. Resolve that output contract, including stat-selection instructions, when implementation starts.

## Audience ownership

The narrative engine owns audience layers, options, semantic descriptions and available combinations in its database. Generate all available buckets regardless of viewer presence. The backend does not supply viewer prompts to this workflow, and receives already-framed bucket versions.

The original 12 buckets are seeds. A retained [prototype](prototypes/bucket_framing/README.md) models flexible definitions; persistence, batching and generation still need integration into this engine. No audience configuration or framing model runs in the user backend.
