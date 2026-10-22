# Decisions

> **In short:** where the built backend follows the [agreed architecture](design/agreed-architecture.md) of 18 October 2026, where it differs and why, and what is left. When a design page and [local/contracts.md](../../local/contracts.md) disagree, the contracts win.

| | |
| --- | --- |
| **Design** | [design/agreed-architecture.md](design/agreed-architecture.md), [design/question-agent-plan.md](design/question-agent-plan.md), [design/replay-plan.md](design/replay-plan.md), [design/custom-calculations.md](design/custom-calculations.md) |
| **Contracts** | [local/contracts.md](../../local/contracts.md) (multi-match, agreed 20 October 2026) |

## 1. Kept from the design

*In short: the boundaries are unchanged.*

- ETL owns standard stats; the backend reads them through GraphQL and never recomputes them.
- Questions never trigger narrative generation; the engine owns bucket wording; the backend routes it unchanged.
- One active session per demo profile; a new tab takes over; chat and pins survive reconnects.
- Custom stats are validated before use; equivalent requests share one calculation; Track is a separate viewer choice.
- Two databases on one Postgres server (Accounts, Match App); Microsoft Agent Framework for agents.

## 2. Changed from the design

*In short: each change has a reason.*

| Design | Built | Why |
| --- | --- | --- |
| One match, `run_id` / cursor snapshots | Many concurrent matches; snapshot `(matchId, seq)` | Multi-match contracts; per-match isolation and purge |
| ETL stats in Cosmos DB | ETL `executeStatsAtSeq` in Azure SQL via DAB | The ETL's built contract |
| Coding agent generates Python in an isolated executor | Goal agent + deterministic compiler to a bounded rule DSL | No generated code runs; validation is exact |
| Viewers' connected buckets enable generation (presence), developer pins | Config-only: per-fixture templates with `enabled` buckets edited in `/dev/` | Generation cost and behaviour are predictable and editable; no process-local presence leases |
| Viewer picks team and style independently | Viewer picks one enabled bucket of the match | No hard-coded choices; only buckets the engine writes for are offered |
| Answers at the newest data | Answers at `min(latest, viewer seq)` | The viewer's picture is held behind live data; answers must not run ahead of it |
| One global session lock | Per-match session locks | Matches must not serialize each other; takeover is per (profile, match) |
| Custom rules over received canonical events (MatchEvent v2) | Custom rules and agents on SPADL actions from ETL (DAB `spadlActions`); MatchEvent v2 kept only for the clock, periods, ticker and gap recovery | One converter (ETL) and one vocabulary across stats, rules, prompts and agents; dropping MatchEvent v2 entirely needs watermark polling and a frontend ticker change |
| Score from the catalogue's goals | Score from MA3 goals and VAR decisions (`rawEvents`) | Built from MA3 before the catalogue subtracted VAR overturns (`009` now does); kept |
| A seq gap waits forever | Buffer, then recover from ETL `canonicalEvents` or record and skip after `stream.gap_timeout_seconds` | One invalid message must not stall a match |
| Prices in each browser | `prices` config table, read by the viewer (`GET /product/prices`) | One edited value for every viewer |
| Chat replay in Phase 2 | Implemented: replay agent + deterministic clip cuts from the feed's HLS | Moved into the hackathon scope on 20 October 2026 |
| Clips in Phase 2 | Moment clips in follows (D3), capture cards (D6) and key-event clips on shared narratives (D7), served as replay-shaped playlists | Demo build, 22 October 2026 |
| One match per viewer | Cross-game questions, pins and follows (D5), each match read at its own position | Demo build: three matches at once |
| Every demo starts at kickoff | Seeded starts restored by a demo-only adapter (`DEMO_SEEDS=1`), adopted as after a restart | Judges see a rich story within seconds; core code never branches on a demo |
| Narrative "new stats" instructions choose default cards | `presentation` config defaults; engine narratives carry no stat ids yet | Engine output contract |

## 3. Open items

*In short: what is still to do.*

- Azure acceptance of this service (PLAN.md §10.4; [deployment](deployment.md)); the follow offer on Azure uses the question model unless `DECISION_*` is added.
- Drop the MatchEvent v2 consumer: clock and periods from `matchWatermarks`, viewer/lab ticker from SPADL actions (frontend change). Until then the ticker keeps canonical names on purpose: a row appears when its event arrives, while its SPADL action is final only at a later `finalSeq`; SPADL also adds dribbles without a source event and has no cards or period markers. Mixing both would relabel rows after they appear.
- Optionally switch scores back to the catalogue's `goals` (it now subtracts VAR overturns).
- Multi-replica ownership, shared delivery and job leases ([architecture §6](architecture.md#6-scaling-boundary)).
- Authentication for `/dev`, `/lab`, `/admin` and per-account question quotas.
- Phase 2: per-viewer pause/rewind.
- An arbitrary-code isolated executor, only if the rule DSL proves insufficient.
