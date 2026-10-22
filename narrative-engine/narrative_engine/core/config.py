from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Settings:
    """Engine tunables; `from_env` reads each as its upper-case name (e.g. MODEL_CONCURRENCY)."""
    last_n_narratives: int = 5        # previous excerpts per bucket passed to the author
    fallback_minutes: int = 10        # match minutes without a narrative step before a scheduled one
    author_concurrency: int = 4       # one match's author calls in flight across its buckets
    model_concurrency: int = 4        # model calls in flight across all matches (summaries first)
    final_period: int = 2             # when MA1 has no capabilities.periods
    targets_poll_seconds: float = 5.0  # how often live matches re-read the audience targets
    backend_cache_seconds: float = 5.0  # targets and prompts are revalidated at most this often
    retry_seconds: float = 5.0        # first retry of failed match work; doubles up to retry_max_seconds
    retry_max_seconds: float = 120.0
    analysis_minutes: int = 5         # match analysis at minutes 5, 10, 15 …, plus half and full time
    storyline_turns: int = 1          # 1: a storyline the analysis opens or resolves gets its own author step

    @classmethod
    def from_env(cls, env):
        return cls(**{f.name: type(f.default)(env[f.name.upper()]) for f in fields(cls) if env.get(f.name.upper())})
