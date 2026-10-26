-- rawEvents.eventSeq: the canonical MatchEvent seq each MA3 row derives from (etl/README.md Contracts), as a
-- column so snapshot reads (eventSeq <= seq) seek an index instead of parsing payloads. statsAtSeq (009's,
-- changed in two places) reads that column for cards and VAR overturns, and treats undeclared MA1
-- capabilities as unavailable: shotOutcomes only when declared true (was: unless declared false). Rerunnable.
IF COL_LENGTH('dbo.rawEvents', 'eventSeq') IS NULL
    ALTER TABLE dbo.rawEvents ADD eventSeq int NULL;
GO
UPDATE dbo.rawEvents SET eventSeq = TRY_CAST(JSON_VALUE(payload, '$.eventSeq') AS int) WHERE eventSeq IS NULL;
GO
IF INDEXPROPERTY(OBJECT_ID('dbo.rawEvents'), 'IX_rawEvents_eventSeq', 'IndexID') IS NULL
    CREATE INDEX IX_rawEvents_eventSeq ON dbo.rawEvents (matchId, eventSeq) INCLUDE (typeId, seq);
GO

-- The catalogue as of one snapshot (matchId, seq), counters as documented in 008. Empty for an unknown or
-- purged match, or for a seq above the watermark or above spadlSeq (retry), never a partial set. Rows: all,
-- home, away, each in displayOrder. Staged: capabilities and definitions are parsed once and the final
-- actions are grouped by what the counters read before they meet the definitions (as one statement, SQL
-- Server re-evaluated JSON and joins per row: ~0.2 s of CPU per call at full time, emulated).
CREATE OR ALTER PROCEDURE dbo.statsAtSeq @matchId nvarchar(64), @seq int
AS
SET NOCOUNT ON;
DECLARE @ok bit = 0, @home nvarchar(64), @capabilities nvarchar(max), @bodyParts bit, @shotOutcomes bit,
        @videoSeconds float, @ownedTotal float;
DECLARE @zones TABLE (zone nvarchar(16) PRIMARY KEY, zoneRank int NOT NULL);
DECLARE @certified TABLE (typeName nvarchar(20) PRIMARY KEY);
DECLARE @defs TABLE (statId nvarchar(40) PRIMARY KEY, label nvarchar(80) NOT NULL, unit nvarchar(8) NOT NULL,
                     definition nvarchar(400) NOT NULL, counter nvarchar(32) NOT NULL, result nvarchar(16) NULL,
                     bodypart nvarchar(16) NULL, zoneRank int NULL, displayOrder int NOT NULL,
                     typesJson nvarchar(400) NULL, needsShotOutcomes bit NOT NULL, needsBodyParts bit NOT NULL);
DECLARE @defTypes TABLE (statId nvarchar(40) NOT NULL, typeName nvarchar(20) NOT NULL, typeOrder int NOT NULL,
                         PRIMARY KEY (typeName, statId));
DECLARE @actions TABLE (teamId nvarchar(64) NOT NULL, typeName nvarchar(20) NOT NULL, resultName nvarchar(16) NOT NULL,
                        bodypartName nvarchar(16) NOT NULL, saved bit NOT NULL, onGoalLine bit NOT NULL,
                        keeperSave bit NOT NULL,
                        startRank int NOT NULL, endRank int NOT NULL, n int NOT NULL);
DECLARE @facts TABLE (statId nvarchar(40) NOT NULL, teamId nvarchar(64) NOT NULL, against bit NOT NULL,
                      hits int NOT NULL, total int NOT NULL);
DECLARE @scopes TABLE (contestantId nvarchar(64) NULL, name nvarchar(100) NOT NULL, scopeOrder int PRIMARY KEY);
DECLARE @counts TABLE (statId nvarchar(40) NOT NULL, scopeOrder int NOT NULL, hits int NOT NULL, total int NOT NULL,
                       PRIMARY KEY (statId, scopeOrder));
DECLARE @owned TABLE (contestantId nvarchar(64) PRIMARY KEY, seconds float NOT NULL);

SELECT @ok = 1, @home = m.homeContestantId, @capabilities = m.capabilities
FROM dbo.matches AS m
LEFT JOIN dbo.matchProgress AS p ON p.matchId = m.matchId
LEFT JOIN dbo.spadlProgress AS sp ON sp.matchId = m.matchId
WHERE m.matchId = @matchId AND @seq >= 0 AND @seq <= ISNULL(p.seq, 0) AND @seq <= ISNULL(sp.seq, 0);

IF @ok = 1
BEGIN
    SET @bodyParts = IIF(JSON_VALUE(@capabilities, '$.bodyParts') = 'true', 1, 0);
    SET @shotOutcomes = IIF(JSON_VALUE(@capabilities, '$.shotOutcomes') = 'true', 1, 0);
    INSERT @certified
    SELECT DISTINCT CAST(value AS nvarchar(20)) FROM OPENJSON(ISNULL(JSON_QUERY(@capabilities, '$.bodyPartActionTypes'), '[]'));
    INSERT @zones VALUES (N'own_box', 0), (N'defensive_third', 1), (N'middle_third', 2), (N'final_third', 3),
                         (N'opp_box', 4);

    INSERT @defTypes
    SELECT d.statId, CAST(t.value AS nvarchar(20)), CAST(t.[key] AS int)
    FROM dbo.statDefinitions AS d
    CROSS APPLY OPENJSON(d.actionTypes) AS t
    WHERE d.enabled = 1;

    INSERT @defs
    SELECT d.statId, d.label, d.unit, d.definition, d.counter, d.result, d.bodypart, z.zoneRank, d.displayOrder,
           (SELECT '[' + STRING_AGG('"' + STRING_ESCAPE(dt.typeName, 'json') + '"', ', ')
                         WITHIN GROUP (ORDER BY dt.typeOrder) + ']'
            FROM @defTypes AS dt WHERE dt.statId = d.statId),
           IIF(EXISTS (SELECT 1 FROM OPENJSON(d.requires) AS r WHERE r.value = 'shotOutcomes'), 1, 0),
           IIF(EXISTS (SELECT 1 FROM OPENJSON(d.requires) AS r WHERE r.value = 'bodyParts'), 1, 0)
    FROM dbo.statDefinitions AS d
    LEFT JOIN @zones AS z ON z.zone = d.zone
    WHERE d.enabled = 1;

    INSERT @actions  -- final at the snapshot, grouped by everything a counter reads
    SELECT a.teamId, a.typeName, a.resultName, a.bodypartName, IIF(a.sourceTypeId = 15, 1, 0),
           IIF(IIF(a.teamId = @home, a.endX, 105e0 - a.endX) >= 105, 1, 0),
           IIF(a.fromShotOffTarget = 0 AND a.defensiveBlock = 0, 1, 0), sz.zoneRank, ez.zoneRank, COUNT(*)
    FROM dbo.spadlActions AS a
    JOIN @zones AS sz ON sz.zone = a.startZone
    JOIN @zones AS ez ON ez.zone = a.endZone
    WHERE a.matchId = @matchId AND a.finalSeq <= @seq
    GROUP BY a.teamId, a.typeName, a.resultName, a.bodypartName, IIF(a.sourceTypeId = 15, 1, 0),
             IIF(IIF(a.teamId = @home, a.endX, 105e0 - a.endX) >= 105, 1, 0),
             IIF(a.fromShotOffTarget = 0 AND a.defensiveBlock = 0, 1, 0), sz.zoneRank, ez.zoneRank;

    INSERT @facts  -- per definition and team; against: credited to the other team
    SELECT d.statId, a.teamId, IIF(d.counter = 'opponent_count', 1, 0),
           SUM(a.n * CASE d.counter
               WHEN 'accuracy' THEN IIF(a.resultName = 'success', 1, 0)
               WHEN 'goals' THEN IIF(a.resultName = 'success', 1, 0)
               WHEN 'on_target' THEN IIF(a.resultName = 'success' OR (a.saved = 1 AND a.onGoalLine = 1), 1, 0)
               WHEN 'blocked' THEN IIF(a.resultName <> 'success' AND a.saved = 1 AND a.onGoalLine = 0, 1, 0)
               WHEN 'keeper_saves' THEN a.keeperSave
               WHEN 'entries' THEN IIF((d.result IS NULL OR a.resultName = d.result)
                                       AND a.startRank < d.zoneRank AND a.endRank >= d.zoneRank, 1, 0)
               ELSE IIF(d.result IS NULL OR a.resultName = d.result, 1, 0)  -- count, opponent_count
           END), SUM(a.n)
    FROM @defs AS d
    JOIN @defTypes AS dt ON dt.statId = d.statId
    JOIN @actions AS a ON a.typeName = dt.typeName
    WHERE d.counter NOT IN ('cards', 'possession', 'retired') AND (d.bodypart IS NULL OR a.bodypartName = d.bodypart)
    GROUP BY d.statId, a.teamId, d.counter;

    INSERT @facts  -- own goals count for the opponent
    SELECT d.statId, a.teamId, 1, SUM(a.n), SUM(a.n)
    FROM @defs AS d
    JOIN @actions AS a ON a.resultName = 'owngoal'
    WHERE d.counter = 'goals'
    GROUP BY d.statId, a.teamId;

    INSERT @facts  -- cards and VAR goal overturns: MA3 rows sent up to the snapshot
    SELECT d.statId, r.contestantId, IIF(d.counter = 'goals', r.ownGoal, 0), IIF(d.counter = 'goals', -1, 1) * COUNT(*),
           COUNT(*)
    FROM @defs AS d
    JOIN (SELECT r.contestantId, r.typeId,
                 IIF(EXISTS (SELECT 1 FROM OPENJSON(r.payload, '$.qualifier') WITH (qualifierId int) AS q
                             WHERE q.qualifierId = 28), 1, 0) AS ownGoal,
                 IIF(EXISTS (SELECT 1 FROM OPENJSON(r.payload, '$.qualifier') WITH (qualifierId int, value nvarchar(64)) AS q
                             WHERE q.qualifierId = 901 AND q.value = N'goal-overturned'), 1, 0) AS overturned
          FROM dbo.rawEvents AS r
          WHERE r.matchId = @matchId AND r.typeId IN (17, 900)
            AND r.eventSeq <= @seq) AS r
      ON (d.counter = 'cards' AND r.typeId = 17) OR (d.counter = 'goals' AND r.typeId = 900 AND r.overturned = 1)
    GROUP BY d.statId, d.counter, r.contestantId, r.ownGoal;

    INSERT @scopes VALUES (NULL, N'Both teams', 0);
    INSERT @scopes
    SELECT t.contestantId, t.name, IIF(t.position = 'home', 1, 2) FROM dbo.matchTeams AS t WHERE t.matchId = @matchId;

    INSERT @counts
    SELECT f.statId, sc.scopeOrder, SUM(f.hits), SUM(f.total)
    FROM @facts AS f
    JOIN @scopes AS sc ON sc.contestantId IS NULL OR (f.against = 0 AND f.teamId = sc.contestantId)
                       OR (f.against = 1 AND f.teamId <> sc.contestantId)
    GROUP BY f.statId, sc.scopeOrder;

    SELECT @videoSeconds = MAX(e.videoSeconds) FROM dbo.canonicalEvents AS e WHERE e.matchId = @matchId AND e.seq <= @seq;
    INSERT @owned
    SELECT p.contestantId, SUM(p.durationSeconds)
    FROM dbo.possessionSamples AS p
    WHERE p.matchId = @matchId AND p.videoSeconds <= @videoSeconds
    GROUP BY p.contestantId;
    SELECT @ownedTotal = SUM(seconds) FROM @owned;
END;

SELECT CONCAT(ISNULL(sc.contestantId, 'all'), ':', d.statId) AS statId,
       d.statId AS kind,
       sc.contestantId,
       CONCAT(sc.name, ' ', d.label) AS label,
       CASE WHEN x.available = 0 THEN NULL
            WHEN d.counter = 'accuracy' THEN dbo.roundHalfEven1(100e0 * c.hits / c.total)
            WHEN d.counter = 'possession'
                THEN dbo.roundHalfEven1(100e0 * IIF(sc.contestantId IS NULL, @ownedTotal, ISNULL(o.seconds, 0)) / @ownedTotal)
            ELSE CAST(ISNULL(c.hits, 0) AS float) END AS value,
       CAST(x.available AS bit) AS available,
       d.unit,
       d.definition,
       ISNULL(d.typesJson, '[]') AS eventTypes,
       CAST(1 AS bit) AS complete
FROM @defs AS d
CROSS JOIN @scopes AS sc
LEFT JOIN @counts AS c ON c.statId = d.statId AND c.scopeOrder = sc.scopeOrder
LEFT JOIN @owned AS o ON o.contestantId = sc.contestantId
CROSS APPLY (SELECT IIF(d.counter <> 'retired'
                        AND (d.needsShotOutcomes = 0 OR @shotOutcomes = 1)
                        AND (d.needsBodyParts = 0 OR @bodyParts = 1 OR NOT EXISTS (
                             SELECT 1 FROM @defTypes AS dt
                             WHERE dt.statId = d.statId AND dt.typeName NOT IN (SELECT typeName FROM @certified)))
                        AND (d.counter <> 'accuracy' OR ISNULL(c.total, 0) > 0)
                        AND (d.counter <> 'possession' OR @ownedTotal > 0), 1, 0) AS available) AS x
ORDER BY sc.scopeOrder, d.displayOrder;
GO
