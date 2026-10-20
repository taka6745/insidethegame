-- Local contract fixture, NOT Stream Analytics or the production ETL schema.
IF DB_ID('matchdata') IS NULL CREATE DATABASE matchdata;
GO
USE matchdata;
GO
IF OBJECT_ID('dbo.rawEvents') IS NULL
CREATE TABLE dbo.rawEvents (
    id nvarchar(100) NOT NULL PRIMARY KEY,
    matchId nvarchar(100) NOT NULL,
    sequence int NOT NULL,
    eventTime nvarchar(40) NOT NULL,
    matchMinute int NOT NULL,
    type nvarchar(80) NOT NULL,
    teamId nvarchar(80) NOT NULL,
    synthetic bit NOT NULL,
    payload nvarchar(max) NOT NULL
);
GO
