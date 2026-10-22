-- Audiences are configuration only: a template's `enabled` flags choose the generation targets.
-- Viewer presence and developer pins are retired; existing pins become enabled flags.
-- An unedited default template enables the demo profiles' three buckets.
UPDATE audience_templates SET pinned_buckets = ARRAY['home:analytical', 'away:casual', 'neutral:simple']
WHERE fixture = 'default' AND revision = 1 AND pinned_buckets = '{}';

UPDATE audience_templates AS t SET revision = t.revision + 1, document = jsonb_set(
  jsonb_set(t.document, '{buckets}', COALESCE((
    SELECT jsonb_agg(b || jsonb_build_object('enabled', (b->>'id') = ANY(t.pinned_buckets)) ORDER BY n)
    FROM jsonb_array_elements(t.document->'buckets') WITH ORDINALITY AS x(b, n)), '[]'::jsonb)),
  -- Viewer labels: `{home}`/`{away}` name the match's teams; other options show their id.
  '{layers}', (
    SELECT jsonb_agg(l || jsonb_build_object('options', (
      SELECT jsonb_agg(CASE WHEN o ? 'label' THEN o ELSE o || jsonb_build_object('label',
        CASE WHEN l->>'id' = 'team' AND o->>'id' IN ('home', 'away') THEN '{' || (o->>'id') || '}'
             ELSE initcap(replace(o->>'id', '_', ' ')) END) END ORDER BY m)
      FROM jsonb_array_elements(l->'options') WITH ORDINALITY AS y(o, m))) ORDER BY n)
    FROM jsonb_array_elements(t.document->'layers') WITH ORDINALITY AS x(l, n)));

ALTER TABLE audience_templates DROP COLUMN pinned_buckets;
ALTER TABLE audience_catalog DROP COLUMN viewer_counts;

-- Each match's catalogue follows its fixture's template (else the default).
UPDATE audience_catalog AS c SET document = t.document, revision = c.revision + 1
FROM audience_templates AS t
WHERE t.fixture = COALESCE((SELECT fixture FROM audience_templates WHERE fixture = c.fixture), 'default')
  AND c.document <> t.document;
