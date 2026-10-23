# Overview

> **In short:** a viewer presses **Start demo**, watches three live matches of the fictional Elephant League (the main game opens first), picks an audience, asks questions, follows a story in this or another match, and plays captured clips with a sting and slow motion. The browser only talks to the backend and demo control; it never calculates statistics or runs a model.

| | |
| --- | --- |
| **Status** | Implemented · unit-tested · headless-checked against the contract mock · run on the local stack · applied to Azure 22 Oct for the Azure test; demo acceptance ([PLAN.md §10.4](../../PLAN.md)) pending |
| **Public URL** | `https://msft-hackathon.koda-software.com` ([edge proxy](../../edge-proxy/README.md) → the Azure frontend) |
| **Pages** | `/` viewer, `/lab/` filter lab, `/dev/` developer console (both gated) |
| **Talks to** | `/viewer-api/` (backend), `/demo-api/` (demo control), `/media/hls/` (feed's HLS origin) |

## 1. Picker and demo

*In short: one demo of three matches at a time, started and advanced from the viewer.*

- `/` lists matches (live, then scheduled, then finished) with status, score and clock; each tab holds one match at `/?match={matchId}`.
- **Start demo** (with a start point: kickoff, or a recorded seed at 20′, HT, 60′, 85′; unrecorded points are disabled) and **Cancel demo** call demo control. A seven-stage pipeline (Feed → Event Hubs → ETL → Service Bus → Narrative engine → Backend → Viewer) lights each stage from real readiness checks.
- After Start demo, or on landing on `/` while a demo is live, the viewer opens the **main game** (Redcastle Town–Port Albion by default); "← All matches" (`/?choose`) keeps the picker. While a demo is on only its matches are listed.
- **Skip ahead** moves every demo match on by the same whole minutes; sessions and follows carry on.
- A seeded start says "The story so far was generated earlier on this pipeline; live from N′."

## 2. Live match

*In short: footage, five stat cards and two conversation tabs, all scoped by match id.*

- Team names, colours and crests come from the match data (MA1 branding); a missing crest falls back to the team code.
- Footage is the match's own HLS (`/media/hls/{matchId}/live.m3u8`); match data is held until the picture reaches it.
- Standard statistics come from ETL through the backend. Tracking a stat replaces the lowest-priority default card; untracking restores it.
- One dropdown lists the match's enabled audience buckets (from the fixture's template). Switching picks which already-framed narratives you see; viewers can switch during a demo.
- A purged match (404 or socket close `4404`) returns the tab to the picker.

## 3. Insights, questions and follows

*In short: shared narratives by default, a private conversation, or one followed story.*

- **Insights** run oldest first with the newest at the bottom; the list stays on the newest unless the viewer has scrolled up. Pivotal key moments show for everyone as short grey lines.
- **Questions** send the seq of the picture the viewer is shown, so answers never cite later events; each answer shows a receipt (facts, tokens, seconds, estimated cost at the backend's configured prices). Enter sends; Shift+Enter adds a line.
- **Customise** opens the follow view: a chat with suggestion chips, a proposal card with Follow, and clarification choices. One story per viewer; while following, the feed shows only that story ("Following since N′") with Stop following.
- **Follow this story?** An answer may offer a follow; Follow opens the follow view with the question. Stat answers never offer.
- **Captured clips:** a follower's story clips, or the bucket's key-event clips, show as preview cards at their moment's clock (crest, minute, event, player, score after). Play opens the playlist on the stage with the sting and slow motion.
- **Cross-match:** content from another live match of the demo is outlined in yellow with that match's teams and crests, never its score.

## 4. Viewers and errors

*In short: each browser is its own viewer; errors are always plain sentences.*

- Each browser keeps an anonymous viewer id; sessions are per (viewer, profile, match). Two people on the same profile never share a conversation; tabs of one browser share it. A new tab, or Reconnect, takes over.
- A viewer never sees raw network or script errors. A match being recorded as a start point says so.
- Assets are fingerprinted; a deploy never needs a hard refresh.
- Profiles are demo identities, not production authentication.
