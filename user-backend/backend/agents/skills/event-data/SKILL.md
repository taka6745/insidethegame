---
name: event-data
description: Interpret football event records using the active adapter's data dictionary, actor roles, units and coverage before defining a custom statistic.
---

Use the accompanying `feed_reference` to understand the data available for this match. It describes normalized records after the event adapter, not a universal Opta schema. Its contract ID and schema fingerprint identify the active version.

Identify the action being measured, the actor credited with that action, and its qualifiers separately. Similar football words can describe opposite participants in an incident. A record's player is the actor defined for its event category; it is not automatically the viewer's subject. Read category definitions and field meanings together.

Distinguish the measure from the topic: action count, recorded distance and completion are different quantities. Preserve the requested scope and ask only when a material ambiguity remains. Everyday wording should be interpreted against the available records. A feed-declared recorded count can answer a broad request without claiming exhaustive physical coverage; label it Recorded and exclude unclassified records. Use one non-overlapping representation from recorded_body_part_event_groups, never add duplicate representations of an action. A familiar football statistic may require fields this feed does not provide; do not invent missing qualifiers or substitute a related statistic.

Use the decision schema for supported outputs and operators. The dictionary explains data meaning and availability; it does not add execution capabilities. Match participants and IDs come from the supplied catalogue. No event history, future events, expected totals or evaluation answers are included in this skill.

The calculation engine supports static field predicates with count or sum, and one composite level: percentage, ratio, difference, or mean of a recorded numeric field. Composites share aggregate inputs. Pass completion excludes unknown outcomes from its denominator; a mean excludes missing numeric measurements and includes zero. It cannot express nested formulas, event sequences, joins, rolling windows or conditions depending on another event. Those limitations apply even when the necessary raw records exist.
