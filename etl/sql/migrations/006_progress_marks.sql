-- Watermark marks from the Azure Stream Analytics job (query.asaql step 9). Each says: event `seq` is
-- complete once events 1..seq, MA3 rows 1..ma3Seq and POS samples 1..sampleId are committed; Azure SQL
-- checks that (sql/azure/asa-progress.sql) and advances matchProgress. The local worker writes
-- matchProgress itself and leaves this table empty.
CREATE TABLE dbo.matchProgressMarks (
    matchId   nvarchar(64) NOT NULL,
    seq       int          NOT NULL,
    ma3Seq    int          NOT NULL,
    sampleId  int          NOT NULL,
    CONSTRAINT PK_matchProgressMarks PRIMARY KEY (matchId, seq, ma3Seq, sampleId) WITH (IGNORE_DUP_KEY = ON)
);
GO

-- The mark check counts MA3 rows by their per-match seq.
CREATE INDEX IX_rawEvents_seq ON dbo.rawEvents (matchId, seq);
GO
