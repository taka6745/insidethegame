-- MA1 knownNames per team (local/README.md Contracts §1): other names fans and commentators use ("the Blues"), as a
-- JSON array of strings, NULL when the feed names none. Readers match a viewer's words against them.

IF COL_LENGTH('dbo.matchTeams', 'knownNames') IS NULL
    ALTER TABLE dbo.matchTeams ADD knownNames nvarchar(max) NULL;
GO
