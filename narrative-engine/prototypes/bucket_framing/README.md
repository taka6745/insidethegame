# Shared bucket framing prototype

**Owned by the narrative engine. Not connected to its production workflow or database yet.**

The retained `models.py` and `framer.py` describe neutral inputs and bucketed authoring. Fetch layer/option descriptions and combinations from the [backend audience API](../../../user-backend/docs/audience-api.md); the seed and authoritative catalogue live there. A neutral source is internal input to this engine; the output published to the user backend is already bucketed.

The framer accepts an injected JSON model adapter (the development experiment used Microsoft Agent Framework). The authoring code has no import or database dependency on the user backend; its future orchestrator reads the configuration API. Its fixture double copies source text; it does not assess writing quality.

Next integration belongs here: fetch a versioned audience catalogue, generate for every available combination, batch calls, and persist/publish the bucketed results. The original 12 combinations are seeds, not a permanent schema restriction. Viewer presence does not determine which configured buckets generate.

The mistaken backend integration remains recoverable in Git commit `882aa2e`; it is no longer active. Its Match App audience/cache tables, if present locally, are untouched but unused.

The model experiment is not cleared for demo quality: 12 versions took about 100 seconds and some added unsupported interpretation. Keep tests of wording separate from transport/schema tests. Do not enable this prototype as a live author without further evaluation.
