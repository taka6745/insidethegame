---
name: event-data
description: Interpret football event records using the active adapter's data dictionary, actor roles, units and coverage before defining a custom statistic.
---

Use the accompanying `feed_reference` to understand the data available for this match. It describes normalized records after the event adapter, not a universal Opta schema. Its contract ID and schema fingerprint identify the active version.

Identify the action being measured, the actor credited with that action, and its qualifiers separately. Similar football words can describe opposite participants in an incident. A record's player is the actor defined for its event category; it is not automatically the viewer's subject. Read category definitions and field meanings together.

Distinguish the measure from the topic: action count, recorded distance and completion are different quantities. Preserve the requested scope and ask when the measure or boundary is unresolved. A familiar football statistic may require fields this feed does not provide; do not invent missing qualifiers or substitute a related statistic.

Use the decision schema for supported outputs and operators. The dictionary explains data meaning and availability; it does not add execution capabilities. Match participants and IDs come from the supplied catalogue. No event history, future events, expected totals or evaluation answers are included in this skill.

The current calculation engine supports independent static field predicates with count or sum. It cannot express ratios, event sequences, joins, rolling windows or conditions depending on another event. Those limitations apply even when the necessary raw records exist.
