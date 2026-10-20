from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    last_n_narratives: int = 5        # previous excerpts per bucket passed to the author
    fallback_minutes: int = 10        # match minutes without a narrative step before a scheduled one
    author_concurrency: int = 4       # author calls in flight across buckets
    presence_stale_seconds: int = 180 # older presence falls back to all 12 buckets
    final_period: int = 2             # extra time is not supported in the demo
