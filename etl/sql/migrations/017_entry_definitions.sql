-- Entry definitions: writers compared box entries (77) with final-third entries (45) as if one were
-- inside the other. The counters are not nested: a final-third entry starts before the final third, a box entry
-- starts anywhere outside the box, including inside the final third. The definitions now say so; the counting is
-- unchanged. reference/catalogue.py applies these after the 008 seed.

DECLARE @definitionUpdates nvarchar(max) = N'[
{"statId": "final_third_entries", "definition": "Successful SPADL passes and dribbles that start before the final third and end in it or in the opponent''s penalty area (team-relative zones). A move from inside the final third into the box is not one, so box entries can outnumber them."},
{"statId": "box_entries", "definition": "Successful SPADL passes and dribbles from outside the opponent''s penalty area into it, including moves that start inside the final third, so they can outnumber final-third entries."}
]';

UPDATE d SET definition = u.definition
FROM dbo.statDefinitions AS d
JOIN OPENJSON(@definitionUpdates) WITH (statId nvarchar(40), definition nvarchar(400)) AS u ON u.statId = d.statId;
