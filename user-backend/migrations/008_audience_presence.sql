ALTER TABLE audience_catalog ADD COLUMN IF NOT EXISTS viewer_managed boolean NOT NULL DEFAULT false;
