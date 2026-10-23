# Football event coverage

**Research guide, 19 October 2026; superseded for implemented events by the [Opta-style v3 contract](../../contracts/README.md) (20 October).** This is our synthetic event contract, inspired by public football definitions; the F24-style export uses public type and qualifier IDs but is not Stats Perform data. A catalog entry does not mean the recording supports it; the recording's capabilities are authoritative.

```text
Native contact / referee decision → replaceable GRF adapter → event + qualifiers
                                                     ↓
                                              ETL stats + history
```

## Implemented native v2

The active adapter now emits taken restarts, referee-whistled fouls/foul-won, offsides, cards, goalkeeper retention claims and half boundaries alongside passes, shots, goals and contacts. Header/foot evidence is retained where trustworthy. Native tests cover rare decisions; the actual match contains only what the simulator produced. Exact coverage lives in each recording's `capabilities`.

## What to capture

The table describes an implementation target. **Raw** means existing capture has useful evidence; **Hook** means native telemetry must expose more information; **Later** means no reliable support is established in this demo.

| Family | Events and useful distinctions | Evidence |
| --- | --- | --- |
| Distribution | Pass; short/long/high; completion; intended/actual recipient; start/end location; distance | Raw contact, requested action and subsequent contact. Cross/through-ball labels need separate classification. |
| Headers | Headed pass, headed shot, headed touch | Raw header function plus explicit requested action; hook actual contact body part. A header is a qualifier, not an additional counted action. |
| Attempts | Shot, goal, own goal; saved, wide, blocked, woodwork; penalty/direct-free-kick attempt | Raw shot/score supports attempts and goals. Outcomes, own-goal identity and goal-frame collision require hooks and attribution tests. |
| Restarts | Kick-off, goal kick, corner, throw-in, free kick, penalty | Raw mode identifies restart category; hook referee buffer for awarded team, taker, location and lifecycle. |
| Offences | Foul, offside; offender/victim; penalty award; advantage; handball | Hook explicit referee decision. Handball support is not established. Free-kick mode alone cannot identify its cause. |
| Discipline | Yellow, second yellow, straight red; dismissal; misconduct reason | Hook referee/card decision and player card transition. Do not invent a reason from card colour. |
| Goalkeeping | Catch, save, parry, punch, claim, smother, keeper distribution, sweeper action | Native goalkeeper retention identifies a claim. The Catch enum is not used by this runtime. A save also needs trustworthy shot-outcome evidence; finer distinctions remain Later. |
| Defending | Tackle, interception, blocked pass, shot block, clearance, recovery | Raw contact/ownership provide evidence; classification needs validated action/context rules. A slide animation is not proof of a tackle. |
| Contests | Ground/aerial duel; winner/loser; take-on; dispossession; challenge | Later: paired opponent/action evidence. Two nearby players do not establish a duel. |
| Ball control | Touch, miscontrol, carry, deflection, loose-ball recovery | Raw touches and ownership. Carry length requires tracking segments; unsuccessful control needs a defensible rule. |
| Creation | Assist, key pass, secondary assist, chance created | Later: link a completed distribution sequence to an attempt/goal; preserve attribution policy. |
| Match lifecycle | Start/end of each half, full time, stoppage/restart, extra time, shootout | Raw phase transitions for this fixture. Extra time and shootout require separate scenario support. |
| Personnel | Starting lineup, bench, substitution, formation change, injury/treatment | Lineup is fixture metadata. The others remain Later until a source explicitly supplies them. |
| Officiating | VAR check, review, overturned decision, disallowed goal, penalty retake, dropped ball, abandonment | Later; do not infer these from a delay, score change or player animation. |
| Analysis | Possession, pass accuracy, shot totals, pressure, territory, xG | ETL owns aggregates. Pressure/territory require a documented tracking rule; xG requires a separately validated model. |

Public [Stats Perform definitions](https://www.statsperform.com/opta-event-definitions/) provide useful checks: offside is separate from foul totals; a shot against the frame is not automatically on target; a goalkeeper contact is not automatically a save. Our adapter must preserve these distinctions rather than filling unknown values with zero.

## Native hooks and remaining extensions

The following are verified in the installed source pinned to GRF commit `3d9e754720a95621bba6475c4d3b0d56fe919014`. Source links are references; active tools modify only a disposable runtime copy, never `legacy/`.

1. **Referee decisions:** emit once in [`Referee::CheckFoul`](https://github.com/google-research/football/blob/3d9e754720a95621bba6475c4d3b0d56fe919014/third_party/gfootball_engine/src/onthepitch/referee.cpp) when `hasBeenProcessed` changes. Capture offender, victim, decision time, foul position, awarded restart and card. `TripNotice` is only a candidate infringement: advantage can cancel the eventual whistle.
2. **Offside:** record the specific `Referee::BallTouched` branch that stops play for an offside recipient. Do not reconstruct this from a free kick or an attacking player's location.
3. **Restarts:** [`RefereeBuffer`](https://github.com/google-research/football/blob/3d9e754720a95621bba6475c4d3b0d56fe919014/third_party/gfootball_engine/src/onthepitch/referee.hpp) exposes mode, team, taker, stop/start times and restart position. Track one restart identity through award, preparation and execution. Count a taken corner only once; keep an awarded-but-untaken corner distinct.
4. **Body part:** [`Humanoid`](https://github.com/google-research/football/blob/3d9e754720a95621bba6475c4d3b0d56fe919014/third_party/gfootball_engine/src/onthepitch/player/humanoid/humanoid.cpp) reads the animation's `touch_bodypart` when applying a contact. Export it alongside current and requested function. Requested action without actual ball contact must never emit a pass or shot.
5. **Goal-frame impact:** [`Ball`](https://github.com/google-research/football/blob/3d9e754720a95621bba6475c4d3b0d56fe919014/third_party/gfootball_engine/src/onthepitch/ball.cpp) contains woodwork collision branches. Capture the actual collision, not every predictive integration step; relate it to an attempt and deduplicate repeated contact.
6. **Cards and dismissals:** use the explicit decision plus the resulting player state; avoid counting both as independent cards. Public [raw observation documentation](https://github.com/google-research/football/blob/3d9e754720a95621bba6475c4d3b0d56fe919014/gfootball/doc/observation.md) also exposes card/active state and seven game modes, but does not supply a complete event feed.

## Event shape and counting

Use stable event IDs, source sequence, revision, period, match time and video time. Preserve actor/team IDs, source evidence and related-event IDs. Keep provider enum values in the adapter. Unknown actor/outcome/body part stays unknown.

Prefer qualifiers for `bodyPart`, `restartType`, `cardType`, recipient, location and outcome. Use a shared `actionId` to relate a restart, pass and contact. A headed corner attempt can therefore answer several filters without becoming several shots.

The existing application represents a scoring attempt once as `goal` and omits its linked `shot` from canonical events. Any expansion must preserve that contract or migrate ETL counting explicitly. Likewise, emitted `touch` records overlap action records; never add touches and passes to estimate total contacts.

The current adapter timestamps a pass when its outcome resolves, so it cannot leak future completion into the live view. A future revision-based feed can retain action time and resolution time separately; replacement revisions must update a counter rather than increment it again.

## Acceptance examples

- A headed pass counts for headed passes and head contacts, not headed shots.
- A headed attempt that scores counts as one goal and one total attempt under ETL's goal-inclusive definition.
- An offside whistle creates an offside and the following restart, never a foul.
- A foul with advantage that continues creates no whistled-foul count; a later card retains its own evidence.
- A corner awarded at full time but never taken does not increment corners taken.
- A keeper catches a cross: catch/claim evidence, no save without a linked shot.
- Repeated contact callbacks or a replayed event ID cannot increase a counter twice.
- A recording with no penalty observed may report zero only if penalty coverage is enabled and the capture is complete.

Rare-event fixtures belong in isolated tests. Do not insert fictional penalties, cards or VAR decisions into the viewer's match just to exercise every category.
