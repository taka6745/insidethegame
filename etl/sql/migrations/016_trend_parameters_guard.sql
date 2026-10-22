-- Trend parameters guard (round 16): dbo.trendMinuteRows reads 13 named parameters, and a missing one turned into
-- NULL and silently emptied its components. A function cannot raise, so the seed procedure refuses any block that
-- does not hold exactly the names the function reads, each with a value, and leaves the table unchanged.

CREATE OR ALTER PROCEDURE dbo.seedTrendParameters @parameters nvarchar(max)
AS
SET NOCOUNT ON;
SET XACT_ABORT ON;
DECLARE @required TABLE (name nvarchar(40) PRIMARY KEY);
INSERT @required (name) VALUES
    ('ball_gap_cap_seconds'), ('ball_last_gap_seconds'), ('long_pass_metres'), ('fast_break_seconds'),
    ('fast_break_metres'), ('momentum_alpha'), ('build_line_metres'), ('press_line_metres'), ('flank_lanes'),
    ('threat_final_third_second'), ('threat_final_third_entry'), ('threat_box_entry'), ('threat_shot');
DECLARE @given TABLE (name nvarchar(40) NULL, value float NULL, meaning nvarchar(300) NULL);
INSERT @given SELECT v.* FROM OPENJSON(@parameters) WITH (name nvarchar(40), value float, meaning nvarchar(300)) AS v;
DECLARE @problem nvarchar(2000) = (
    SELECT STRING_AGG(problem, '; ') FROM (
        SELECT 'missing ' + r.name AS problem FROM @required AS r WHERE NOT EXISTS (SELECT 1 FROM @given AS g WHERE g.name = r.name)
        UNION ALL SELECT 'unknown ' + ISNULL(g.name, '(no name)') FROM @given AS g WHERE NOT EXISTS (SELECT 1 FROM @required AS r WHERE r.name = g.name)
        UNION ALL SELECT 'no value for ' + g.name FROM @given AS g WHERE g.name IS NOT NULL AND (g.value IS NULL OR g.meaning IS NULL)
        UNION ALL SELECT 'duplicate ' + g.name FROM @given AS g WHERE g.name IS NOT NULL GROUP BY g.name HAVING COUNT(*) > 1
    ) AS p);
IF @problem IS NOT NULL
BEGIN
    DECLARE @message nvarchar(2048) = CONCAT(N'trendParameters not changed: ', @problem);
    THROW 51016, @message, 1;
END;
BEGIN TRANSACTION;
MERGE dbo.trendParameters AS t
USING @given AS s
ON t.name = s.name
WHEN MATCHED THEN UPDATE SET value = s.value, meaning = s.meaning
WHEN NOT MATCHED BY TARGET THEN INSERT (name, value, meaning) VALUES (s.name, s.value, s.meaning)
WHEN NOT MATCHED BY SOURCE THEN DELETE;
COMMIT;
GO
