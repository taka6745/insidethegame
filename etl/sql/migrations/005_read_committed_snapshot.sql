-- Readers (DAB, statsAtSeq) see the last committed version instead of taking shared locks, so they
-- never deadlock with the stream's batch transactions. Azure SQL has this on by default, so it is
-- skipped there and its open connections (Stream Analytics, DAB) are not rolled back.
IF NOT EXISTS (SELECT 1 FROM sys.databases WHERE database_id = DB_ID() AND is_read_committed_snapshot_on = 1)
    ALTER DATABASE CURRENT SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
GO
