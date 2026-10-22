# Overview

> **In short:** three rendered 90-minute matches with real-club illustrative lineups, and a feed service that plays any of them as a live match, several at once, into Event Hubs and HLS. It also starts the three-match judge demo, from kick-off or a seeded start point. Implemented and tested; runs in the local Docker stack; Azure applied 22 Oct (acceptance pending).

| | |
| --- | --- |
| **Status** | Generator implemented (offline, macOS); feed implemented, tested and run with three concurrent matches locally; Start demo, main game and seeded runs unit-tested and run on the local stack (22 Oct); Azure applied 22 Oct, acceptance pending |
| **Data** | Synthetic, simulated with Google Research Football (Apache-2.0); labelled `synthetic: true` everywhere; not Stats Perform data |
| **Out** | Event Hubs `match-events` (MA1, `MatchEvent` v2, MA3, POS); HLS over HTTP |
| **Consumers** | ETL (`etl-stream`), user backend; viewers through nginx (`/media/hls/`) |

## 1. What it does

*In short: render once offline, replay live many times.*

1. **Generate (offline):** `grf_demo/` renders a match in real time, derives Opta-style events from native contacts and referee decisions, and packages aligned video as HLS.
2. **Replay (live):** the feed mints a `matchId` per run, sends MA1 a minute before kickoff, then every item at video pace, and publishes each HLS segment once it has played.
3. **Demo:** `POST /demo/start {point}` starts the configured fixtures once (main game first, staggered). A seeded point creates the runs waiting; demo control restores every owner, then releases them to play on from that point ([feed §2a](components/feed.md#2a-demo-and-seeds)).

## 2. Inputs and outputs

*In short: recordings and media in; one stream and one HLS origin out.*

| Direction | What | Contract |
| --- | --- | --- |
| In | `recordings/<fixture>-grf.json` | [opta-events.md](opta-events.md), [recordings](../recordings/README.md) |
| In | `.local/grf-demo-<fixture>-90/hls/` (optional, ignored) | [feed §5](components/feed.md#5-recordings-and-media) |
| Out | Event Hubs `match-events`, partition key `matchId` | [local contracts §2](../../local/contracts.md#2-matchevent-v2), [ETL contracts](../../etl/contracts/README.md) |
| Out | `/hls/{matchId}/live.m3u8` | [local contracts §6](../../local/contracts.md#6-live-media-hls) |
| Admin | Recordings, runs, purge, demo settings and start (dev only; demo control calls it) | [local contracts §7](../../local/contracts.md#7-feed-admin-api-dev-only) |

## 3. Glossary

*In short: the words the pages use.*

| Term | Meaning |
| --- | --- |
| Fixture | Catalogue id of a recording, e.g. `chelsea-united` |
| Run | One live playback of a fixture; its `matchId` is `{fixture}-{run8}` |
| Canonical event | One recording event; sent as `MatchEvent` v2 with `seq` = its order |
| `videoSeconds` | Seconds after kickoff on the match video; the feed's clock |
| Tombstone | Permanent record that a `matchId` was purged |
| Start point | Match-clock point a demo may start from: kick-off, 20′, second half, 60′, 85′ |
| Main game | `demo_settings.main_fixture` (default `arsenal-liverpool`): starts first, opens by default |
| Seed | Every owner's rows recorded at a start point by a *held* run; restored under a new `matchId` |
