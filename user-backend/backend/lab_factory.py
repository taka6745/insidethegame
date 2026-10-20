"""Composition root. Swap providers here without changing routes or rule logic."""
import os

from .adapters.hls_publisher import HlsPublisher
from .adapters.replay_source import FixtureEventSource
from .adapters.product_demo import load_product_demo
from .agents.workflow import workflow_from_env
from .repositories.lab import PostgresLabRepository
from .services.lab import FilterLabService


def create_filter_lab(store):
    content = load_product_demo()
    source = FixtureEventSource(content=content, filename='product-demo.json') if os.getenv('DEMO_RECORDING_URL') else FixtureEventSource()
    lab = FilterLabService(source, PostgresLabRepository(store),
                            workflow_from_env(data_reference=source.data_reference()),
                            local_llm=os.environ.get("LOCAL_LLM_MODE", "fixture") == "local",
                            max_calculations=int(os.getenv("FILTER_MAX_CALCULATIONS", "10000")),
                            recording_editable=not bool(os.getenv('DEMO_RECORDING_URL')),
                            initial_recording=(content, "product-demo.json"))
    lab.hls = HlsPublisher.from_env()
    return lab
