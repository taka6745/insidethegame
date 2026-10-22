-- Azure SQL only: what local_stream does in Python, for the rows Stream Analytics writes. Applied by
-- `python -m devtools azure-setup` after the migrations (rerunnable); tests/test_sql_azure.py runs it.
-- Stream Analytics writes each output separately, append-only, and Microsoft documents INSTEAD OF INSERT
-- triggers as the way to intercept those inserts. Here they:
--   gate:     drop rows of purged matches (tombstones). An MA1 stamped before the purge-all cut-off is
--             tombstoned with its rows; other rows stamped before it need a stored MA1.
--   progress: turn matchProgressMarks into matchProgress (matchWatermarks, statsAtSeq) once events
--             1..seq, MA3 rows 1..ma3Seq and POS samples 1..sampleId are committed, and set matches.status.
-- spadlActions and spadlProgress come from the SPADL post-processor (spadl/worker.py), which checks the
-- tombstone itself under the same lock; a late MA1 below also deletes them.
-- Inserts hold the purge lock shared, the purge (local_stream/repository.py) exclusive; progress holds a
-- per-match lock, so the last of several concurrent output batches sees all of them.

CREATE OR ALTER PROCEDURE dbo.asaProgress @matchId nvarchar(64)
AS
SET NOCOUNT ON;
DECLARE @lock nvarchar(255) = N'etl-progress:' + @matchId;
EXEC sp_getapplock @Resource = @lock, @LockMode = N'Exclusive', @LockOwner = N'Transaction';
IF NOT EXISTS (SELECT 1 FROM dbo.matches WHERE matchId = @matchId)
    RETURN;
DECLARE @current int = ISNULL((SELECT seq FROM dbo.matchProgress WHERE matchId = @matchId), 0), @seq int;
-- Committed prefixes: the highest n with 1..n all stored (0 when 1 is missing).
DECLARE @events int = ISNULL((SELECT MIN(e.seq) FROM dbo.canonicalEvents AS e
    WHERE e.matchId = @matchId AND e.seq >= 1 AND NOT EXISTS (SELECT 1 FROM dbo.canonicalEvents AS n
        WHERE n.matchId = @matchId AND n.seq = e.seq + 1)
      AND EXISTS (SELECT 1 FROM dbo.canonicalEvents AS f WHERE f.matchId = @matchId AND f.seq = 1)), 0);
DECLARE @ma3 int = ISNULL((SELECT MIN(r.seq) FROM dbo.rawEvents AS r
    WHERE r.matchId = @matchId AND r.seq >= 1 AND NOT EXISTS (SELECT 1 FROM dbo.rawEvents AS n
        WHERE n.matchId = @matchId AND n.seq = r.seq + 1)
      AND EXISTS (SELECT 1 FROM dbo.rawEvents AS f WHERE f.matchId = @matchId AND f.seq = 1)), 0);
DECLARE @samples int = ISNULL((SELECT MIN(p.sampleId) FROM dbo.possessionSamples AS p
    WHERE p.matchId = @matchId AND p.sampleId >= 1 AND NOT EXISTS (SELECT 1 FROM dbo.possessionSamples AS n
        WHERE n.matchId = @matchId AND n.sampleId = p.sampleId + 1)
      AND EXISTS (SELECT 1 FROM dbo.possessionSamples AS f WHERE f.matchId = @matchId AND f.sampleId = 1)), 0);
SELECT @seq = MAX(k.seq)
FROM dbo.matchProgressMarks AS k
WHERE k.matchId = @matchId AND k.seq > @current AND k.seq <= @events AND k.ma3Seq <= @ma3 AND k.sampleId <= @samples;
IF @seq IS NOT NULL
BEGIN
    MERGE dbo.matchProgress AS t USING (SELECT @matchId AS matchId, @seq AS seq) AS s ON t.matchId = s.matchId
    WHEN MATCHED THEN UPDATE SET seq = s.seq
    WHEN NOT MATCHED THEN INSERT (matchId, seq) VALUES (s.matchId, s.seq);
    DELETE dbo.matchProgressMarks WHERE matchId = @matchId AND seq <= @seq;
    SET @current = @seq;
END;
-- live once an event is stored; finished once the watermark reaches the final period_end.
UPDATE m SET status = s.status
FROM dbo.matches AS m
CROSS APPLY (SELECT CASE
    WHEN EXISTS (SELECT 1 FROM dbo.canonicalEvents AS e
                 WHERE e.matchId = m.matchId AND e.seq <= @current AND e.deleted = 0 AND e.eventType = 'period_end'
                   AND e.periodId = TRY_CAST(JSON_VALUE(m.capabilities, '$.periods') AS int)) THEN 'finished'
    WHEN EXISTS (SELECT 1 FROM dbo.canonicalEvents AS e WHERE e.matchId = m.matchId) THEN 'live'
    ELSE m.status END AS status) AS s
WHERE m.matchId = @matchId AND m.status <> 'finished' AND m.status <> s.status;
GO

CREATE OR ALTER TRIGGER dbo.asa_matches ON dbo.matches INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    -- An MA1 sent before the last purge of every match: tombstone it and drop its rows.
    DECLARE @late TABLE (matchId nvarchar(64) PRIMARY KEY);
    INSERT @late (matchId)
    SELECT DISTINCT i.matchId FROM inserted AS i CROSS JOIN dbo.purgeCutoff AS c
    WHERE CAST(SWITCHOFFSET(TRY_CAST(JSON_VALUE(i.payload, '$.timeStamp') AS datetimeoffset(3)), '+00:00') AS datetime2(3))
          < c.cutoffAt;
    INSERT dbo.purgedMatches (matchId) SELECT matchId FROM @late;
    DELETE dbo.matchTeams WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.matchPlayers WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.canonicalEvents WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.possessionSamples WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.rawEvents WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.keyEvents WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.minuteStats WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.matchProgressMarks WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.spadlActions WHERE matchId IN (SELECT matchId FROM @late);
    DELETE dbo.spadlProgress WHERE matchId IN (SELECT matchId FROM @late);
    INSERT dbo.matches (
        matchId, description, homeContestantId, homeName, awayContestantId, awayName, scheduledKickoff,
        synthetic, payload, fixture, sourceMatchId, runId, capabilities)
    SELECT matchId, description, homeContestantId, homeName, awayContestantId, awayName, scheduledKickoff,
           synthetic, payload, fixture, sourceMatchId, runId, capabilities
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId);
    DECLARE @matchId nvarchar(64);
    DECLARE batch CURSOR LOCAL FAST_FORWARD FOR SELECT DISTINCT matchId FROM inserted ORDER BY matchId;
    OPEN batch;
    FETCH NEXT FROM batch INTO @matchId;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC dbo.asaProgress @matchId;
        FETCH NEXT FROM batch INTO @matchId;
    END;
    CLOSE batch;
    DEALLOCATE batch;
END;
GO

CREATE OR ALTER TRIGGER dbo.asa_matchTeams ON dbo.matchTeams INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    INSERT dbo.matchTeams (
        matchId, contestantId, position, name, shortName, code, knownNames, primaryColour, secondaryColour,
        crestAssetId)
    SELECT matchId, contestantId, position, name, shortName, code, knownNames, primaryColour, secondaryColour,
           crestAssetId
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId);
END;
GO

CREATE OR ALTER TRIGGER dbo.asa_matchPlayers ON dbo.matchPlayers INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    INSERT dbo.matchPlayers (
        matchId, playerId, contestantId, name, shirtNumber, position, starter)
    SELECT matchId, playerId, contestantId, name, shirtNumber, position, starter
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId);
END;
GO

CREATE OR ALTER TRIGGER dbo.asa_canonicalEvents ON dbo.canonicalEvents INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    INSERT dbo.canonicalEvents (
        matchId, seq, eventId, revision, eventType, teamId, playerId, bodyPart, periodId, matchTimeSeconds,
        outcome, distanceMetres, deleted, videoSeconds, x, y, possessionId, qualifiers, eventTime)
    SELECT matchId, seq, eventId, revision, eventType, teamId, playerId, bodyPart, periodId, matchTimeSeconds,
           outcome, distanceMetres, deleted, videoSeconds, x, y, possessionId, qualifiers, eventTime
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId)
      AND (i.eventTime >= ISNULL((SELECT cutoffAt FROM dbo.purgeCutoff), '0001-01-01')
             OR EXISTS (SELECT 1 FROM dbo.matches AS m WHERE m.matchId = i.matchId));
    DECLARE @matchId nvarchar(64);
    DECLARE batch CURSOR LOCAL FAST_FORWARD FOR SELECT DISTINCT matchId FROM inserted ORDER BY matchId;
    OPEN batch;
    FETCH NEXT FROM batch INTO @matchId;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC dbo.asaProgress @matchId;
        FETCH NEXT FROM batch INTO @matchId;
    END;
    CLOSE batch;
    DEALLOCATE batch;
END;
GO

CREATE OR ALTER TRIGGER dbo.asa_possessionSamples ON dbo.possessionSamples INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    INSERT dbo.possessionSamples (
        matchId, sampleId, periodId, videoSeconds, durationSeconds, contestantId, eventSeq, eventTime)
    SELECT matchId, sampleId, periodId, videoSeconds, durationSeconds, contestantId, eventSeq, eventTime
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId)
      AND (i.eventTime >= ISNULL((SELECT cutoffAt FROM dbo.purgeCutoff), '0001-01-01')
             OR EXISTS (SELECT 1 FROM dbo.matches AS m WHERE m.matchId = i.matchId));
    DECLARE @matchId nvarchar(64);
    DECLARE batch CURSOR LOCAL FAST_FORWARD FOR SELECT DISTINCT matchId FROM inserted ORDER BY matchId;
    OPEN batch;
    FETCH NEXT FROM batch INTO @matchId;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC dbo.asaProgress @matchId;
        FETCH NEXT FROM batch INTO @matchId;
    END;
    CLOSE batch;
    DEALLOCATE batch;
END;
GO

CREATE OR ALTER TRIGGER dbo.asa_rawEvents ON dbo.rawEvents INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    INSERT dbo.rawEvents (
        matchId, id, seq, eventId, typeId, periodId, timeMin, timeSec, contestantId, playerId, outcome, x, y,
        eventTime, payload, eventSeq)
    SELECT matchId, id, seq, eventId, typeId, periodId, timeMin, timeSec, contestantId, playerId, outcome, x,
           y, eventTime, payload, eventSeq
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId)
      AND (i.eventTime >= ISNULL((SELECT cutoffAt FROM dbo.purgeCutoff), '0001-01-01')
             OR EXISTS (SELECT 1 FROM dbo.matches AS m WHERE m.matchId = i.matchId));
    DECLARE @matchId nvarchar(64);
    DECLARE batch CURSOR LOCAL FAST_FORWARD FOR SELECT DISTINCT matchId FROM inserted ORDER BY matchId;
    OPEN batch;
    FETCH NEXT FROM batch INTO @matchId;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC dbo.asaProgress @matchId;
        FETCH NEXT FROM batch INTO @matchId;
    END;
    CLOSE batch;
    DEALLOCATE batch;
END;
GO

CREATE OR ALTER TRIGGER dbo.asa_keyEvents ON dbo.keyEvents INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    INSERT dbo.keyEvents (
        matchId, id, keyType, detail, typeId, contestantId, playerId, periodId, timeMin, timeSec, eventTime,
        relatedEventId)
    SELECT matchId, id, keyType, detail, typeId, contestantId, playerId, periodId, timeMin, timeSec, eventTime,
           relatedEventId
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId)
      AND (i.eventTime >= ISNULL((SELECT cutoffAt FROM dbo.purgeCutoff), '0001-01-01')
             OR EXISTS (SELECT 1 FROM dbo.matches AS m WHERE m.matchId = i.matchId));
END;
GO

CREATE OR ALTER TRIGGER dbo.asa_minuteStats ON dbo.minuteStats INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    INSERT dbo.minuteStats (
        matchId, contestantId, periodId, timeMin, windowEnd, passes, passesCompleted, shots, shotsOnTarget,
        goals, ownGoals, corners, fouls, yellowCards, redCards, events)
    SELECT matchId, contestantId, periodId, timeMin, windowEnd, passes, passesCompleted, shots, shotsOnTarget,
           goals, ownGoals, corners, fouls, yellowCards, redCards, events
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId)
      AND (i.windowEnd >= ISNULL((SELECT cutoffAt FROM dbo.purgeCutoff), '0001-01-01')
             OR EXISTS (SELECT 1 FROM dbo.matches AS m WHERE m.matchId = i.matchId));
END;
GO

CREATE OR ALTER TRIGGER dbo.asa_matchProgressMarks ON dbo.matchProgressMarks INSTEAD OF INSERT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction';
    INSERT dbo.matchProgressMarks (
        matchId, seq, ma3Seq, sampleId)
    SELECT matchId, seq, ma3Seq, sampleId
    FROM inserted AS i
    WHERE NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS p WHERE p.matchId = i.matchId)
      -- Redelivered marks at or below the watermark are spent; storing them only lengthens progress's delete.
      AND i.seq > ISNULL((SELECT g.seq FROM dbo.matchProgress AS g WHERE g.matchId = i.matchId), 0);
    DECLARE @matchId nvarchar(64);
    DECLARE batch CURSOR LOCAL FAST_FORWARD FOR SELECT DISTINCT matchId FROM inserted ORDER BY matchId;
    OPEN batch;
    FETCH NEXT FROM batch INTO @matchId;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC dbo.asaProgress @matchId;
        FETCH NEXT FROM batch INTO @matchId;
    END;
    CLOSE batch;
    DEALLOCATE batch;
END;
GO
