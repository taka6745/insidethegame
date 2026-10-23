-- Seeds. hold_seconds: a recording run stops sending at this video second (a seed is captured
-- there). resume_seconds: a run created from a seed waits, unlaunched, until every owner has restored the seed;
-- release then starts its clock at this video second, with everything before it taken as delivered.
ALTER TABLE runs ADD COLUMN hold_seconds double precision, ADD COLUMN resume_seconds double precision;
