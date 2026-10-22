---
name: event-data
description: Interpret football match data as SPADL actions (types, results, body parts, team-relative zones and locations) using the active data reference before defining a custom statistic.
---

Use the accompanying `feed_reference` to understand the data available for this match. It is the SPADL dictionary (contract `spadl-v1`): every on-the-ball action has one action type, a result, a body part, start and end locations in team-relative metres and zones. Cards and possession are outside SPADL and come from catalogue statistics.

Identify the action being measured, the actor credited with it, and its result separately. A shot and its save are two actions by opposite teams; a foul is credited to the offender. A record's player is the actor of that action, never the receiver or the opponent.

Distinguish the measure from the topic: action count, ball distance (start to end) and completion are different quantities. Passes mean the whole pass family unless the viewer says open-play passes. Zones and x/y are relative to the acting team, which always attacks towards x = 105. Body parts are complete only for the types the reference lists as classified; otherwise count only actions whose body part was observed and label the result Recorded. A familiar football statistic may need data SPADL does not record (aerial duels, recoveries, touches, xG): do not substitute a related statistic.

Use the decision schema for supported outputs and operators; its enums are the only SPADL values. No action history, future actions, expected totals or evaluation answers are included in this skill.

The calculation engine supports static field predicates with count or sum, and one composite level: percentage, ratio, difference, or mean of distance. Composites share aggregate inputs. It cannot express nested formulas, action sequences, joins, rolling windows or conditions depending on another action.
