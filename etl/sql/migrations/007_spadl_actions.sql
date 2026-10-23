-- SPADL actions (local/contracts/README.md §3, etl/contracts/spadl-action.schema.json), converted from MA3 rawEvents
-- by the SPADL post-processor (spadl/worker.py; a task in etl-stream locally, ETL_ROLE=spadl on Azure).
-- Only final actions are stored: a snapshot (matchId, s) reads actions with finalSeq <= s, for s <= spadlSeq.

CREATE TABLE dbo.spadlActions (
    matchId           nvarchar(64)  NOT NULL,
    actionId          int           NOT NULL,  -- SPADL action_id: 0, 1, 2… per match; never renumbered
    originalEventId   bigint        NULL,      -- MA3 id (Opta event id); null for inserted dribbles
    periodId          int           NOT NULL,
    timeSeconds       float         NOT NULL,  -- seconds since the start of the period
    teamId            nvarchar(64)  NOT NULL,
    playerId          nvarchar(120) NULL,
    startX            float         NOT NULL,  -- metres, 0..105; SPADL frame: the home team attacks towards x = 105
    startY            float         NOT NULL,  -- metres, 0..68
    endX              float         NOT NULL,
    endY              float         NOT NULL,
    typeId            int           NOT NULL,
    typeName          nvarchar(20)  NOT NULL,
    resultId          int           NOT NULL,
    resultName        nvarchar(16)  NOT NULL,
    bodypartId        int           NOT NULL,
    bodypartName      nvarchar(16)  NOT NULL,
    -- Extensions
    seq               int           NOT NULL,  -- canonical seq of the source MA3 row (MA3 eventSeq); dribbles: the next action's
    finalSeq          int           NOT NULL,  -- canonical seq after which this row cannot change
    sourceEventId     nvarchar(120) NULL,      -- MA3 sourceEventId (the canonical event_id)
    sourceTypeId      int           NULL,      -- Opta type of the source MA3 row
    clockSeconds      float         NOT NULL,  -- match clock (period 2 starts at 2700)
    videoSeconds      float         NULL,
    possessionId      int           NULL,
    bodypartObserved  bit           NOT NULL,  -- a qualifier names the body part (else SPADL's default)
    startZone         nvarchar(16)  NOT NULL,  -- relative to the acting team: own_box, defensive_third,
    endZone           nvarchar(16)  NOT NULL,  --   middle_third, final_third, opp_box
    ingestedAt        datetime2(3)  NOT NULL CONSTRAINT DF_spadlActions_ingestedAt DEFAULT sysutcdatetime(),
    CONSTRAINT PK_spadlActions PRIMARY KEY (matchId, actionId) WITH (IGNORE_DUP_KEY = ON)
);
CREATE INDEX IX_spadlActions_finalSeq ON dbo.spadlActions (matchId, finalSeq);
GO

-- Highest canonical seq the SPADL post-processor has converted: every action with finalSeq <= seq is stored.
CREATE TABLE dbo.spadlProgress (
    matchId  nvarchar(64) NOT NULL PRIMARY KEY,
    seq      int          NOT NULL
);
GO

CREATE OR ALTER VIEW dbo.matchWatermarks AS
SELECT p.matchId, p.seq, e.periodId, e.matchTimeSeconds AS clockSeconds, e.videoSeconds, e.eventTime,
       ISNULL(s.seq, 0) AS spadlSeq
FROM dbo.matchProgress AS p
JOIN dbo.canonicalEvents AS e ON e.matchId = p.matchId AND e.seq = p.seq
LEFT JOIN dbo.spadlProgress AS s ON s.matchId = p.matchId;
GO
