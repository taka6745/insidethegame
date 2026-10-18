"""Composition root. Swap providers here without changing routes or rule logic."""
import os

from .adapters.replay_source import FixtureEventSource
from .adapters.product_demo import load_product_demo
from .agents.workflow import workflow_from_env
from .repositories.lab import PostgresLabRepository
from .services.lab import FilterLabService


def create_filter_lab(store):
    source = FixtureEventSource()
    return FilterLabService(source, PostgresLabRepository(store),
                            workflow_from_env(data_reference=source.adapter.data_reference()),
                            local_llm=os.environ.get("LOCAL_LLM_MODE", "fixture") == "local",
                            initial_recording=(load_product_demo(), "product-demo.json"))
