-- Local stream worker state (not part of the Azure pipeline): Event Hubs checkpoints,
-- closed windows and a notification outbox written in the same transaction as the rows.
-- Guarded so a partly applied run can be retried.

IF OBJECT_ID('dbo.localStreamCheckpoints') IS NULL
CREATE TABLE dbo.localStreamCheckpoints (
    partitionId     nvarchar(16) NOT NULL PRIMARY KEY,
    sequenceNumber  bigint       NOT NULL
);
GO

IF OBJECT_ID('dbo.localStreamWindows') IS NULL
CREATE TABLE dbo.localStreamWindows (
    matchId      nvarchar(64) NOT NULL PRIMARY KEY,
    closedUntil  datetime2(3) NOT NULL
);
GO

IF OBJECT_ID('dbo.localStreamOutbox') IS NULL
CREATE TABLE dbo.localStreamOutbox (
    seq               bigint IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    messageId         nvarchar(200) NOT NULL,
    notificationType  nvarchar(32)  NOT NULL,
    body              nvarchar(max) NOT NULL,
    createdAt         datetime2(3)  NOT NULL CONSTRAINT DF_localStreamOutbox_createdAt DEFAULT sysutcdatetime(),
    sentAt            datetime2(3)  NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_localStreamOutbox_messageId')
CREATE UNIQUE INDEX UX_localStreamOutbox_messageId ON dbo.localStreamOutbox (messageId) WITH (IGNORE_DUP_KEY = ON);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_localStreamOutbox_unsent')
CREATE INDEX IX_localStreamOutbox_unsent ON dbo.localStreamOutbox (seq) WHERE sentAt IS NULL;
GO
