-- Stat catalogue (local/contracts.md §4): 29 kinds × 3 scopes = 87 frozen stat ids, served by
-- statsAtSeq(@matchId, @seq) from canonical events and possession samples. Definitions are
-- configuration; reference/catalogue.py reads the seed below and is the executable expectation.
--
-- counter: type (latest non-deleted events of eventTypes), head (body part head), keeper_save
--   (no defensiveBlock/fromShotOffTarget qualifier), shot_on_target (goal, or outcome saved/on_target),
--   shot_blocked (outcome blocked), success (outcome success), pass_accuracy (success / resolved, %),
--   possession (share of POS ownership seconds up to the event's video time, %).
-- requires (all must hold, else available = 0 and value null): eventTypes (each type is in MA1
--   capabilities.eventTypes), shotOutcomes (capabilities.shotOutcomes is not false), bodyParts
--   (capabilities.bodyParts, or each type in capabilities.bodyPartEventTypes), shotTypes (not a
--   requirement: drops goal from eventTypes when capabilities.shotsIncludeScoringAttempts).

CREATE TABLE dbo.statDefinitions (
    statId        nvarchar(40)  NOT NULL CONSTRAINT PK_statDefinitions PRIMARY KEY,  -- the kind, e.g. goals
    label         nvarchar(80)  NOT NULL,
    unit          nvarchar(8)   NOT NULL,
    definition    nvarchar(400) NOT NULL,
    eventTypes    nvarchar(400) NOT NULL CONSTRAINT CK_statDefinitions_eventTypes CHECK (ISJSON(eventTypes) = 1),
    counter       nvarchar(32)  NOT NULL CONSTRAINT CK_statDefinitions_counter CHECK (counter IN
                  ('type', 'head', 'keeper_save', 'shot_on_target', 'shot_blocked', 'success', 'pass_accuracy', 'possession')),
    requires      nvarchar(400) NOT NULL CONSTRAINT CK_statDefinitions_requires CHECK (ISJSON(requires) = 1),
    displayOrder  int           NOT NULL,
    enabled       bit           NOT NULL CONSTRAINT DF_statDefinitions_enabled DEFAULT 1
);
GO

DECLARE @definitions nvarchar(max) = N'[
{"statId": "goals", "label": "goals", "unit": "", "definition": "Observed goal events; latest non-deleted revisions.", "eventTypes": ["goal"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "shots", "label": "shots", "unit": "", "definition": "Observed shot, goal events; latest non-deleted revisions.", "eventTypes": ["shot", "goal"], "counter": "type", "requires": ["eventTypes", "shotTypes"]},
{"statId": "passes", "label": "passes", "unit": "", "definition": "Observed pass events; latest non-deleted revisions.", "eventTypes": ["pass"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "corners", "label": "corners", "unit": "", "definition": "Restarts actually taken, not merely awarded; latest non-deleted revisions.", "eventTypes": ["corner"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "cards", "label": "cards", "unit": "", "definition": "Observed card events; latest non-deleted revisions.", "eventTypes": ["card"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "tackles", "label": "tackles", "unit": "", "definition": "Observed tackle events; latest non-deleted revisions.", "eventTypes": ["tackle"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "interceptions", "label": "interceptions", "unit": "", "definition": "Observed interception events; latest non-deleted revisions.", "eventTypes": ["interception"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "fouls", "label": "fouls", "unit": "", "definition": "Whistled fouls committed; excludes offsides and companion foul-won records.", "eventTypes": ["foul"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "fouls_won", "label": "fouls won", "unit": "", "definition": "Observed foul_won events; latest non-deleted revisions.", "eventTypes": ["foul_won"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "offsides", "label": "offsides", "unit": "", "definition": "Observed offside events; latest non-deleted revisions.", "eventTypes": ["offside"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "throw_ins", "label": "throw ins", "unit": "", "definition": "Restarts actually taken, not merely awarded; latest non-deleted revisions.", "eventTypes": ["throw_in"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "free_kicks", "label": "free kicks", "unit": "", "definition": "Restarts actually taken, not merely awarded; latest non-deleted revisions.", "eventTypes": ["free_kick"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "goal_kicks", "label": "goal kicks", "unit": "", "definition": "Restarts actually taken, not merely awarded; latest non-deleted revisions.", "eventTypes": ["goal_kick"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "kick_offs", "label": "kick offs", "unit": "", "definition": "Restarts actually taken, not merely awarded; latest non-deleted revisions.", "eventTypes": ["kick_off"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "penalties", "label": "penalties", "unit": "", "definition": "Restarts actually taken, not merely awarded; latest non-deleted revisions.", "eventTypes": ["penalty"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "keeper_claims", "label": "keeper claims", "unit": "", "definition": "Observed keeper_claim events; latest non-deleted revisions.", "eventTypes": ["keeper_claim"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "clearances", "label": "clearances", "unit": "", "definition": "Observed clearance events; latest non-deleted revisions.", "eventTypes": ["clearance"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "take_ons", "label": "take ons", "unit": "", "definition": "Observed take_on events; latest non-deleted revisions.", "eventTypes": ["take_on"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "ball_recoveries", "label": "ball recoveries", "unit": "", "definition": "Observed ball_recovery events; latest non-deleted revisions.", "eventTypes": ["ball_recovery"], "counter": "type", "requires": ["eventTypes"]},
{"statId": "headed_passes", "label": "headed passes", "unit": "", "definition": "Head contacts among pass records; requires complete body-part coverage for each category.", "eventTypes": ["pass"], "counter": "head", "requires": ["eventTypes", "bodyParts"]},
{"statId": "headed_shots", "label": "headed shots", "unit": "", "definition": "Head contacts among shot, goal records; requires complete body-part coverage for each category.", "eventTypes": ["shot", "goal"], "counter": "head", "requires": ["eventTypes", "bodyParts", "shotTypes"]},
{"statId": "headed_contacts", "label": "headed contacts", "unit": "", "definition": "Head contacts among touch records; requires complete body-part coverage for each category.", "eventTypes": ["touch"], "counter": "head", "requires": ["eventTypes", "bodyParts"]},
{"statId": "saves", "label": "saves", "unit": "", "definition": "Goalkeeper saves of on-target attempts; excludes outfield blocks.", "eventTypes": ["save"], "counter": "keeper_save", "requires": ["eventTypes"]},
{"statId": "shots_on_target", "label": "shots on target", "unit": "", "definition": "Goals plus non-goal shots explicitly recorded saved/on_target.", "eventTypes": ["shot", "goal"], "counter": "shot_on_target", "requires": ["eventTypes", "shotOutcomes"]},
{"statId": "blocked_shots", "label": "blocked shots", "unit": "", "definition": "Team''s non-goal shots recorded blocked.", "eventTypes": ["shot"], "counter": "shot_blocked", "requires": ["eventTypes", "shotOutcomes"]},
{"statId": "aerials_won", "label": "aerials won", "unit": "", "definition": "aerial records with success outcome; latest non-deleted revisions.", "eventTypes": ["aerial"], "counter": "success", "requires": ["eventTypes"]},
{"statId": "successful_take_ons", "label": "successful take ons", "unit": "", "definition": "take_on records with success outcome; latest non-deleted revisions.", "eventTypes": ["take_on"], "counter": "success", "requires": ["eventTypes"]},
{"statId": "pass_accuracy", "label": "pass accuracy", "unit": "%", "definition": "Successful resolved passes / all resolved passes (%); unknown outcomes excluded.", "eventTypes": ["pass"], "counter": "pass_accuracy", "requires": []},
{"statId": "possession", "label": "possession", "unit": "%", "definition": "Share of measured native simulation ball-ownership seconds; unowned ball excluded.", "eventTypes": [], "counter": "possession", "requires": []}
]';
INSERT dbo.statDefinitions (statId, label, unit, definition, eventTypes, counter, requires, displayOrder)
SELECT d.statId, d.label, d.unit, d.definition, d.eventTypes, d.counter, d.requires, CAST(d.[key] AS int) + 1
FROM (SELECT j.[key], v.*
      FROM OPENJSON(@definitions) AS j
      CROSS APPLY OPENJSON(j.value) WITH (
          statId nvarchar(40), label nvarchar(80), unit nvarchar(8), definition nvarchar(400),
          eventTypes nvarchar(max) AS JSON, counter nvarchar(32), requires nvarchar(max) AS JSON) AS v) AS d;
GO

-- Python round(x, 1) on a double: the exact binary value, half to even on exact ties.
CREATE OR ALTER FUNCTION dbo.roundHalfEven1 (@x float) RETURNS float
WITH SCHEMABINDING
AS
BEGIN
    DECLARE @tenths decimal(26, 20) = CAST(@x AS decimal(25, 20)) * 10;
    DECLARE @floor decimal(6, 0) = FLOOR(@tenths);
    RETURN CAST((@floor + CASE WHEN @tenths - @floor > 0.5 THEN 1
                               WHEN @tenths - @floor < 0.5 THEN 0
                               ELSE @floor % 2 END) / 10 AS float);
END;
GO

-- The catalogue as of one snapshot (matchId, seq). Empty for an unknown or purged match, or for a
-- seq above the watermark (retry), never a partial set. Rows: all, home, away, each in displayOrder.
CREATE OR ALTER PROCEDURE dbo.statsAtSeq @matchId nvarchar(64), @seq int
AS
SET NOCOUNT ON;
WITH snapshot AS (
    SELECT m.matchId,
           ISNULL(JSON_QUERY(m.capabilities, '$.eventTypes'), '[]') AS supportedTypes,
           ISNULL(JSON_QUERY(m.capabilities, '$.bodyPartEventTypes'), '[]') AS bodyPartTypes,
           IIF(JSON_VALUE(m.capabilities, '$.bodyParts') = 'true', 1, 0) AS bodyParts,
           IIF(JSON_VALUE(m.capabilities, '$.shotOutcomes') = 'false', 0, 1) AS shotOutcomes,
           IIF(JSON_VALUE(m.capabilities, '$.shotsIncludeScoringAttempts') = 'true', 1, 0) AS scoringShots
    FROM dbo.matches AS m
    LEFT JOIN dbo.matchProgress AS p ON p.matchId = m.matchId
    WHERE m.matchId = @matchId AND @seq BETWEEN 0 AND ISNULL(p.seq, 0)
),
defs AS (
    SELECT d.*,
           IIF(EXISTS (SELECT 1 FROM OPENJSON(d.requires) AS r WHERE r.value = 'eventTypes'), 1, 0) AS needsTypes,
           IIF(EXISTS (SELECT 1 FROM OPENJSON(d.requires) AS r WHERE r.value = 'shotOutcomes'), 1, 0) AS needsShotOutcomes,
           IIF(EXISTS (SELECT 1 FROM OPENJSON(d.requires) AS r WHERE r.value = 'bodyParts'), 1, 0) AS needsBodyParts,
           IIF(EXISTS (SELECT 1 FROM OPENJSON(d.requires) AS r WHERE r.value = 'shotTypes'), 1, 0) AS shotTypes
    FROM dbo.statDefinitions AS d
    WHERE d.enabled = 1
),
defTypes AS (  -- each definition's counted event types for this match
    SELECT d.statId, CAST(t.value AS nvarchar(40)) AS eventType, CAST(t.[key] AS int) AS typeOrder
    FROM defs AS d
    CROSS JOIN snapshot AS s
    CROSS APPLY OPENJSON(d.eventTypes) AS t
    WHERE NOT (t.value = 'goal' AND d.shotTypes = 1 AND s.scoringShots = 1)
),
latest AS (
    SELECT e.*, ROW_NUMBER() OVER (PARTITION BY e.eventId ORDER BY e.revision DESC, e.seq) AS rn
    FROM dbo.canonicalEvents AS e
    JOIN snapshot AS s ON s.matchId = e.matchId
    WHERE e.seq <= @seq
),
observed AS (
    SELECT *, JSON_VALUE(qualifiers, '$.defensiveBlock') AS defensiveBlock,
           JSON_VALUE(qualifiers, '$.fromShotOffTarget') AS fromShotOffTarget
    FROM latest WHERE rn = 1 AND deleted = 0
),
scopes AS (
    SELECT CAST(NULL AS nvarchar(64)) AS contestantId, CAST(N'Both teams' AS nvarchar(100)) AS name, 0 AS scopeOrder
    FROM snapshot
    UNION ALL
    SELECT t.contestantId, t.name, IIF(t.position = 'home', 1, 2)
    FROM dbo.matchTeams AS t
    JOIN snapshot AS s ON s.matchId = t.matchId
),
hits AS (  -- one row per definition, scope and counted event
    SELECT d.statId, sc.contestantId,
           CASE d.counter
               WHEN 'type' THEN 1
               WHEN 'head' THEN IIF(o.bodyPart = 'head', 1, 0)
               WHEN 'keeper_save' THEN IIF((o.defensiveBlock IS NULL OR o.defensiveBlock IN ('false', '')
                                                OR TRY_CAST(o.defensiveBlock AS float) = 0)
                                           AND (o.fromShotOffTarget IS NULL OR o.fromShotOffTarget IN ('false', '')
                                                OR TRY_CAST(o.fromShotOffTarget AS float) = 0), 1, 0)
               WHEN 'shot_on_target' THEN IIF(o.eventType = 'goal' OR o.outcome IN ('saved', 'on_target'), 1, 0)
               WHEN 'shot_blocked' THEN IIF(o.outcome = 'blocked', 1, 0)
               ELSE IIF(o.outcome = 'success', 1, 0)  -- success, pass_accuracy
           END AS hit,
           IIF(o.outcome IN ('success', 'failure'), 1, 0) AS resolved
    FROM observed AS o
    JOIN defTypes AS dt ON dt.eventType = o.eventType
    JOIN defs AS d ON d.statId = dt.statId
    JOIN scopes AS sc ON sc.contestantId IS NULL OR sc.contestantId = o.teamId
),
counts AS (
    SELECT statId, contestantId, SUM(hit) AS hits, SUM(resolved) AS resolved
    FROM hits GROUP BY statId, contestantId
),
videoClock AS (
    SELECT MAX(e.videoSeconds) AS videoSeconds
    FROM dbo.canonicalEvents AS e
    JOIN snapshot AS s ON s.matchId = e.matchId
    WHERE e.seq <= @seq
),
owned AS (
    SELECT p.contestantId, SUM(p.durationSeconds) AS seconds
    FROM dbo.possessionSamples AS p
    JOIN snapshot AS s ON s.matchId = p.matchId
    CROSS JOIN videoClock AS v
    WHERE p.videoSeconds <= v.videoSeconds
    GROUP BY p.contestantId
),
ownedTotal AS (
    SELECT SUM(seconds) AS seconds FROM owned
),
rowsOut AS (
    SELECT d.statId AS kind, d.label, d.unit, d.definition, d.counter, d.displayOrder,
           sc.contestantId, sc.name, sc.scopeOrder,
           ISNULL(c.hits, 0) AS hits, ISNULL(c.resolved, 0) AS resolved,
           IIF(sc.contestantId IS NULL, ot.seconds, ISNULL(o.seconds, 0)) AS ownedSeconds, ot.seconds AS totalSeconds,
           (SELECT '[' + STRING_AGG('"' + STRING_ESCAPE(dt.eventType, 'json') + '"', ', ')
                         WITHIN GROUP (ORDER BY dt.typeOrder) + ']'
            FROM defTypes AS dt WHERE dt.statId = d.statId) AS typesJson,
           IIF((d.needsTypes = 0 OR NOT EXISTS (
                    SELECT 1 FROM defTypes AS dt WHERE dt.statId = d.statId
                      AND dt.eventType NOT IN (SELECT CAST(value AS nvarchar(40)) FROM OPENJSON(s.supportedTypes))))
               AND (d.needsShotOutcomes = 0 OR s.shotOutcomes = 1)
               AND (d.needsBodyParts = 0 OR s.bodyParts = 1 OR NOT EXISTS (
                    SELECT 1 FROM defTypes AS dt WHERE dt.statId = d.statId
                      AND dt.eventType NOT IN (SELECT CAST(value AS nvarchar(40)) FROM OPENJSON(s.bodyPartTypes))))
               AND (d.counter <> 'pass_accuracy' OR ISNULL(c.resolved, 0) > 0)
               AND (d.counter <> 'possession' OR ot.seconds > 0), 1, 0) AS available
    FROM defs AS d
    CROSS JOIN snapshot AS s
    CROSS JOIN scopes AS sc
    CROSS JOIN ownedTotal AS ot
    LEFT JOIN counts AS c ON c.statId = d.statId
         AND (c.contestantId = sc.contestantId OR (c.contestantId IS NULL AND sc.contestantId IS NULL))
    LEFT JOIN owned AS o ON o.contestantId = sc.contestantId
)
SELECT CONCAT(ISNULL(contestantId, 'all'), ':', kind) AS statId,
       kind,
       contestantId,
       CONCAT(name, ' ', label) AS label,
       CASE WHEN available = 0 THEN NULL
            WHEN counter = 'pass_accuracy' THEN dbo.roundHalfEven1(100e0 * hits / resolved)
            WHEN counter = 'possession' THEN dbo.roundHalfEven1(100e0 * ownedSeconds / totalSeconds)
            ELSE CAST(hits AS float) END AS value,
       CAST(available AS bit) AS available,
       unit,
       definition,
       ISNULL(typesJson, '[]') AS eventTypes,
       CAST(1 AS bit) AS complete
FROM rowsOut
ORDER BY scopeOrder, displayOrder;
GO
