-- Multi-match audiences. A template per feed fixture is configuration (definitions and developer
-- pins); each match gets its own catalogue, whose enabled buckets = template pins + connected viewers.
CREATE TABLE IF NOT EXISTS audience_templates (
    fixture text PRIMARY KEY CHECK (fixture ~ '^[a-z0-9-]{1,55}$'),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    document jsonb NOT NULL,
    pinned_buckets text[] NOT NULL DEFAULT '{}'
);
-- `default` applies to every fixture without its own template.
INSERT INTO audience_templates (fixture, document) VALUES ('default', '{"layers":[{"id":"team","description":"Which side the viewer supports for this match.","options":[{"id":"home","description":"Supports the home team in this match. Frame relevance from their perspective without biasing facts."},{"id":"away","description":"Supports the away team in this match. Frame relevance from their perspective without biasing facts."},{"id":"neutral","description":"No team allegiance. Give an even-handed view of both teams."}]},{"id":"fan_style","description":"How to explain the same match facts.","options":[{"id":"simple","description":"New to football. Use short sentences and explain necessary football terms."},{"id":"casual","description":"Follows football casually. Explain the main significance in accessible language."},{"id":"experienced","description":"Knows football well. Use familiar football terminology without basic explanations."},{"id":"analytical","description":"Prefers evidence and tactical detail. Use only statistics and interpretations present in the source."}]}],"buckets":[{"id":"home:simple","selections":{"team":"home","fan_style":"simple"},"enabled":false},{"id":"home:casual","selections":{"team":"home","fan_style":"casual"},"enabled":false},{"id":"home:experienced","selections":{"team":"home","fan_style":"experienced"},"enabled":false},{"id":"home:analytical","selections":{"team":"home","fan_style":"analytical"},"enabled":false},{"id":"away:simple","selections":{"team":"away","fan_style":"simple"},"enabled":false},{"id":"away:casual","selections":{"team":"away","fan_style":"casual"},"enabled":false},{"id":"away:experienced","selections":{"team":"away","fan_style":"experienced"},"enabled":false},{"id":"away:analytical","selections":{"team":"away","fan_style":"analytical"},"enabled":false},{"id":"neutral:simple","selections":{"team":"neutral","fan_style":"simple"},"enabled":false},{"id":"neutral:casual","selections":{"team":"neutral","fan_style":"casual"},"enabled":false},{"id":"neutral:experienced","selections":{"team":"neutral","fan_style":"experienced"},"enabled":false},{"id":"neutral:analytical","selections":{"team":"neutral","fan_style":"analytical"},"enabled":false}]}'::jsonb)
ON CONFLICT DO NOTHING;
-- The single-run catalogue rows belonged to retired run ids.
DROP TABLE IF EXISTS audience_catalog;
CREATE TABLE audience_catalog (
    match_id text PRIMARY KEY REFERENCES received_matches(match_id) ON DELETE CASCADE,
    fixture text NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    document jsonb NOT NULL,
    viewer_counts jsonb NOT NULL DEFAULT '{}'
);
