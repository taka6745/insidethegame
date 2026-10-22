-- Retired single-run narrative cache (neutral narratives, per-bucket variants, framing leases).
-- No code reads or writes them: the narrative engine owns framing and live narratives arrive in
-- engine_narratives. No CASCADE, so an unexpected dependent object fails the migration loudly.
DROP TABLE IF EXISTS narrative_framing_leases, narrative_variants, neutral_narratives;
