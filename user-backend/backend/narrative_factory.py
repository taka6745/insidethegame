"""Composition root; fixture and real-model framing are explicitly separate."""
import os

from .adapters.llm import LocalJsonModel
from .agents.narrative_framer import FixtureNarrativeFramer, NarrativeFramer
from .repositories.narratives import NarrativeRepository
from .services.narratives import NarrativeService


def create_narrative_service(store, match_id):
    mode = os.getenv('NARRATIVE_FRAMING_MODE', 'fixture')
    if mode not in {'fixture', 'local'}:
        raise ValueError('NARRATIVE_FRAMING_MODE must be fixture or local')
    framer = (NarrativeFramer(LocalJsonModel.from_env(
        name='shared_narrative_framer', max_output_tokens=int(os.getenv('NARRATIVE_MAX_OUTPUT_TOKENS', '6000'))))
              if mode == 'local' else FixtureNarrativeFramer())
    return NarrativeService(NarrativeRepository(store), framer, match_id,
                            batch_size=int(os.getenv('NARRATIVE_BATCH_SIZE', '4')),
                            max_variants=int(os.getenv('NARRATIVE_MAX_VARIANTS', '48')),
                            timeout=float(os.getenv('NARRATIVE_TIMEOUT_SECONDS', '60')))
