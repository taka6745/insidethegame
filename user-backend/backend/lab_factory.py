"""Composition root. Swap providers here without changing routes or rule logic."""
import os

from .adapters.replay_source import FixtureEventSource
from .agents.workflow import workflow_from_env
from .repositories.lab import PostgresLabRepository
from .services.lab import FilterLabService


def create_filter_lab(store):
    return FilterLabService(FixtureEventSource(), PostgresLabRepository(store), workflow_from_env(),
                            local_llm=os.environ.get("LOCAL_LLM_MODE", "fixture") == "local")
