-- Tables written by the Stream Analytics job.
-- Stream Analytics delivers at least once; IGNORE_DUP_KEY makes replayed inserts no-ops.

CREATE TABLE dbo.matches (
    matchId           nvarchar(64)  NOT NULL,
    description       nvarchar(200) NULL,
    homeContestantId  nvarchar(64)  NOT NULL,
    homeName          nvarchar(100) NULL,
    awayContestantId  nvarchar(64)  NOT NULL,
    awayName          nvarchar(100) NULL,
    scheduledKickoff  datetime2(3)  NULL,
    synthetic         bit           NOT NULL,
    payload           nvarchar(max) NOT NULL,  -- full MA1 message, including lineups and provenance
    ingestedAt        datetime2(3)  NOT NULL CONSTRAINT DF_matches_ingestedAt DEFAULT sysutcdatetime(),
    CONSTRAINT PK_matches PRIMARY KEY (matchId) WITH (IGNORE_DUP_KEY = ON)
);
GO

CREATE TABLE dbo.rawEvents (
    matchId       nvarchar(64)  NOT NULL,
    id            bigint        NOT NULL,  -- Opta id, unique per event
    seq           int           NOT NULL,
    eventId       int           NOT NULL,  -- Opta per-contestant sequence
    typeId        int           NOT NULL,
    periodId      int           NOT NULL,
    timeMin       int           NOT NULL,
    timeSec       int           NOT NULL,
    contestantId  nvarchar(64)  NOT NULL,
    playerId      nvarchar(64)  NULL,
    outcome       tinyint       NOT NULL,
    x             float         NULL,
    y             float         NULL,
    eventTime     datetime2(3)  NOT NULL,  -- wall-clock timeStamp
    payload       nvarchar(max) NOT NULL,  -- full MA3 message, including qualifiers
    ingestedAt    datetime2(3)  NOT NULL CONSTRAINT DF_rawEvents_ingestedAt DEFAULT sysutcdatetime(),
    CONSTRAINT PK_rawEvents PRIMARY KEY (matchId, id) WITH (IGNORE_DUP_KEY = ON)
);
CREATE INDEX IX_rawEvents_matchClock ON dbo.rawEvents (matchId, periodId, timeMin, timeSec);
GO

CREATE TABLE dbo.keyEvents (
    matchId         nvarchar(64) NOT NULL,
    id              bigint       NOT NULL,
    keyType         nvarchar(32) NOT NULL,  -- Goal, OwnGoal, PenaltyAwarded, PenaltyMissed, RedCard, VarOverturn
    detail          nvarchar(32) NULL,      -- penalty, conceded, second-yellow, goal-overturned, own-goal-overturned
    typeId          int          NOT NULL,
    contestantId    nvarchar(64) NOT NULL,  -- Opta convention: the event player's team
    playerId        nvarchar(64) NULL,
    periodId        int          NOT NULL,
    timeMin         int          NOT NULL,
    timeSec         int          NOT NULL,
    eventTime       datetime2(3) NOT NULL,
    relatedEventId  int          NULL,      -- qualifier 55: eventId of the related event (e.g. the overturned goal)
    ingestedAt      datetime2(3) NOT NULL CONSTRAINT DF_keyEvents_ingestedAt DEFAULT sysutcdatetime(),
    CONSTRAINT PK_keyEvents PRIMARY KEY (matchId, id) WITH (IGNORE_DUP_KEY = ON)
);
GO

-- One row per contestant, match minute and tumbling window. Windows normally hold
-- one match minute; if they do not, the view still sums partial rows correctly.
CREATE TABLE dbo.minuteStats (
    matchId          nvarchar(64) NOT NULL,
    contestantId     nvarchar(64) NOT NULL,
    periodId         int          NOT NULL,
    timeMin          int          NOT NULL,
    windowEnd        datetime2(3) NOT NULL,
    passes           int NOT NULL,
    passesCompleted  int NOT NULL,
    shots            int NOT NULL,
    shotsOnTarget    int NOT NULL,
    goals            int NOT NULL,  -- VAR overturn contributes -1
    ownGoals         int NOT NULL,  -- scored into own net; the view credits the opponent
    corners          int NOT NULL,
    fouls            int NOT NULL,
    yellowCards      int NOT NULL,
    redCards         int NOT NULL,
    events           int NOT NULL,
    ingestedAt       datetime2(3) NOT NULL CONSTRAINT DF_minuteStats_ingestedAt DEFAULT sysutcdatetime(),
    CONSTRAINT PK_minuteStats PRIMARY KEY (matchId, contestantId, periodId, timeMin, windowEnd) WITH (IGNORE_DUP_KEY = ON)
);
GO
