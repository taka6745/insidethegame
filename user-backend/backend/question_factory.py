"""Question composition: replace the local bridge when real snapshot APIs are available."""
import os
from .adapters.hls_media import HlsMedia
from .adapters.question_data import GraphQLQuestionData
from .agents.question import QuestionAgent
from .agents.question_fixture import FixtureQuestionAgent
from .repositories.questions import QuestionRepository
from .services.question_snapshot import LabSnapshotProvider
from .services.questions import QuestionService
from .services.replay import ReplayBuilder


def create_question_service(store, lab, *, brokers=None):
    bridge = 'demo' if os.getenv('DEMO_RECORDING_URL') else os.getenv('ENABLE_DEV_FEED') == '1'
    if brokers:
        from .adapters.broker_data import BrokerQuestionData
        match_data = BrokerQuestionData(os.environ['ETL_GRAPHQL_URL'], operation='stats')
        narratives = BrokerQuestionData(os.environ['NARRATIVE_GRAPHQL_URL'], operation='compact', inbox=brokers.inbox)
    else:
        match_data = GraphQLQuestionData(os.environ['ETL_GRAPHQL_URL'], bridge=bridge)
        narratives = GraphQLQuestionData(os.environ['NARRATIVE_GRAPHQL_URL'], bridge=bridge)
    return QuestionService(QuestionRepository(store),LabSnapshotProvider(lab),
        match_data, narratives,
        QuestionAgent() if lab.local_llm else FixtureQuestionAgent(),lab.planner,
        timeout=float(os.getenv('QUESTION_TIMEOUT_SECONDS','90')),
        max_active=int(os.getenv('QUESTION_MAX_ACTIVE','4')), replays=ReplayBuilder(HlsMedia.from_env()))
