-- Multi-match read models (local/contracts/README.md §1–5): match identity from MA1, teams and players,
-- canonical MatchEvent v2 storage, POS possession samples, the per-match watermark and purge tombstones.

ALTER TABLE dbo.matches ADD
    fixture        nvarchar(55)  NULL,  -- feed catalogue id
    sourceMatchId  nvarchar(120) NULL,  -- the recording's own id (provenance only)
    runId          nvarchar(64)  NULL,  -- feed run; matchId = {fixture}-{first 8 hex of runId}
    status         nvarchar(16)  NOT NULL CONSTRAINT DF_matches_status DEFAULT 'scheduled',  -- scheduled, live, finished
    capabilities   nvarchar(max) NULL;  -- MA1 capabilities JSON
GO

CREATE TABLE dbo.matchTeams (
    matchId          nvarchar(64)  NOT NULL,
    contestantId     nvarchar(64)  NOT NULL,
    position         nvarchar(8)   NOT NULL,  -- home, away
    name             nvarchar(100) NULL,
    shortName        nvarchar(60)  NULL,
    code             nvarchar(8)   NULL,
    primaryColour    nvarchar(16)  NULL,
    secondaryColour  nvarchar(16)  NULL,
    crestAssetId     nvarchar(64)  NULL,
    CONSTRAINT PK_matchTeams PRIMARY KEY (matchId, contestantId) WITH (IGNORE_DUP_KEY = ON)
);
GO

CREATE TABLE dbo.matchPlayers (
    matchId       nvarchar(64)  NOT NULL,
    playerId      nvarchar(120) NOT NULL,
    contestantId  nvarchar(64)  NOT NULL,
    name          nvarchar(100) NULL,
    shirtNumber   int           NULL,
    position      nvarchar(8)   NULL,
    starter       bit           NULL,
    CONSTRAINT PK_matchPlayers PRIMARY KEY (matchId, playerId) WITH (IGNORE_DUP_KEY = ON)
);
GO

-- One row per MatchEvent v2 (seq 1, 2, 3… per match). Corrections are new seqs with a higher revision.
CREATE TABLE dbo.canonicalEvents (
    matchId           nvarchar(64)  NOT NULL,
    seq               int           NOT NULL,
    eventId           nvarchar(120) NOT NULL,
    revision          int           NOT NULL,
    eventType         nvarchar(40)  NOT NULL,
    teamId            nvarchar(64)  NULL,
    playerId          nvarchar(120) NULL,
    bodyPart          nvarchar(16)  NULL,
    periodId          int           NOT NULL,
    matchTimeSeconds  int           NOT NULL,
    outcome           nvarchar(40)  NULL,
    distanceMetres    float         NULL,
    deleted           bit           NOT NULL,
    videoSeconds      float         NULL,
    x                 float         NULL,
    y                 float         NULL,
    possessionId      int           NULL,
    qualifiers        nvarchar(max) NOT NULL,  -- typed qualifier map (JSON)
    eventTime         datetime2(3)  NOT NULL,  -- envelope timeStamp (wall clock)
    ingestedAt        datetime2(3)  NOT NULL CONSTRAINT DF_canonicalEvents_ingestedAt DEFAULT sysutcdatetime(),
    CONSTRAINT PK_canonicalEvents PRIMARY KEY (matchId, seq) WITH (IGNORE_DUP_KEY = ON)
);
CREATE INDEX IX_canonicalEvents_event ON dbo.canonicalEvents (matchId, eventId, revision);
GO

-- POS: measured ball ownership, one row per sample.
CREATE TABLE dbo.possessionSamples (
    matchId          nvarchar(64) NOT NULL,
    sampleId         int          NOT NULL,
    periodId         int          NOT NULL,
    videoSeconds     float        NOT NULL,  -- end of the sample on the match video clock
    durationSeconds  float        NOT NULL,  -- seconds the contestant owned the ball in the sample
    contestantId     nvarchar(64) NOT NULL,
    eventSeq         int          NULL,      -- latest canonical seq sent before the sample (informational)
    eventTime        datetime2(3) NOT NULL,
    ingestedAt       datetime2(3) NOT NULL CONSTRAINT DF_possessionSamples_ingestedAt DEFAULT sysutcdatetime(),
    CONSTRAINT PK_possessionSamples PRIMARY KEY (matchId, sampleId) WITH (IGNORE_DUP_KEY = ON)
);
CREATE INDEX IX_possessionSamples_video ON dbo.possessionSamples (matchId, videoSeconds) INCLUDE (contestantId, durationSeconds);
GO

-- Highest canonical seq whose event, MA3 rows and earlier POS samples are all committed.
CREATE TABLE dbo.matchProgress (
    matchId  nvarchar(64) NOT NULL PRIMARY KEY,
    seq      int          NOT NULL
);
GO

CREATE OR ALTER VIEW dbo.matchWatermarks AS
SELECT p.matchId, p.seq, e.periodId, e.matchTimeSeconds AS clockSeconds, e.videoSeconds, e.eventTime
FROM dbo.matchProgress AS p
JOIN dbo.canonicalEvents AS e ON e.matchId = p.matchId AND e.seq = p.seq;
GO

-- Purge tombstones (permanent; matchIds are never reused) and the purge-all cut-off.
CREATE TABLE dbo.purgedMatches (
    matchId   nvarchar(64) NOT NULL,
    purgedAt  datetime2(3) NOT NULL CONSTRAINT DF_purgedMatches_purgedAt DEFAULT sysutcdatetime(),
    CONSTRAINT PK_purgedMatches PRIMARY KEY (matchId) WITH (IGNORE_DUP_KEY = ON)
);
GO

CREATE TABLE dbo.purgeCutoff (
    singleton  bit          NOT NULL CONSTRAINT PK_purgeCutoff PRIMARY KEY CONSTRAINT CK_purgeCutoff CHECK (singleton = 1),
    cutoffAt   datetime2(3) NOT NULL  -- an MA1 stamped before it is dropped
);
GO
