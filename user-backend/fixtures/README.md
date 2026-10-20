# Synthetic match fixtures

**Hand-authored development data. No real match, player data, footage or Opta content.** The JSON is inspired by football event feeds; it is not Opta's schema or a compatible vendor parser. Team names are illustrative.

| File | Purpose |
| --- | --- |
| `match.json` | Seven starting events, then the ordered scenario in the backend's normalized shape |
| `opta-style.jsonl` | Eleven replay messages: eight events and three prewritten bucket narratives |

```text
20′ join → 21′ header + goal → 25′ red card → 30′ corner
         → 33′ equaliser → 34′ VAR cancellation → 47′ header + save
```

Each JSONL line has `synthetic: true`, `kind` and `payload`. An event carries `matchId`, stable `eventId`, `sequence`, `typeName`, `periodId`, match-clock `timeMin`/`timeSec`, `teamId`, and qualifiers such as `bodyPart` or `relatedEventId`. Narratives carry their exact team/style bucket and optional ordered `stat_ids`.

The fake ETL maps `CHE`/`MUN` to `home`/`away`. It counts shots, cards and valid goals; a cancellation references its goal ID. Possession is a supplied constant, not inferred from passes. These counts are test definitions, not official football statistics. The header pin counts **all headed touches**, including passes and shots; narrower goals need a separate calculation.

Starting headed touches: **2**. Final: **4**. Final score: **Chelsea 1–0 United**. The cancelled goal remains in history alongside its correction. Duplicate event IDs do not increment counts; conflicting reuse is rejected. Narrative semantic deduplication belongs upstream and is not simulated; replaying twice can repeat narrative history.

`./dev reset backend` resets the fake services. `./dev replay backend --interval 1` sends one message per second. Match times are retained; this is accelerated testing, not real-time match-clock replay. Tests verify that both files describe the same normalized events; update both when editing a scenario.
