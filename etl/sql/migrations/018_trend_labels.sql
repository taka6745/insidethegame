-- Plain trend labels: writers copied two analytics terms into fan-facing text. Writers see each
-- trend's label and meaning, never its id, so the labels themselves are plain football words; the measures are
-- unchanged. reference/trends.py applies these after the newest @trendDefinitions seed.

DECLARE @trendLabels nvarchar(max) = N'[
{"trendId": "field_tilt", "label": "share of final-third play"},
{"trendId": "def_height", "label": "defending height"}
]';

UPDATE d SET label = l.label
FROM dbo.trendDefinitions AS d
JOIN OPENJSON(@trendLabels) WITH (trendId nvarchar(40), label nvarchar(80)) AS l ON l.trendId = d.trendId;
