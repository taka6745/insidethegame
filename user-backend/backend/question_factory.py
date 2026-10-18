"""Question composition: replace the local bridge when real snapshot APIs are available."""
import os
from .adapters.question_data import GraphQLQuestionData
from .agents.question import QuestionAgent
from .agents.question_fixture import FixtureQuestionAgent
from .repositories.questions import QuestionRepository
from .services.question_snapshot import LabSnapshotProvider
from .services.questions import QuestionService


def create_question_service(store, lab):
    return QuestionService(QuestionRepository(store),LabSnapshotProvider(lab),
        GraphQLQuestionData(os.environ['ETL_GRAPHQL_URL'],bridge=os.getenv('ENABLE_DEV_FEED') == '1'),
        GraphQLQuestionData(os.environ['NARRATIVE_GRAPHQL_URL'],bridge=os.getenv('ENABLE_DEV_FEED') == '1'),
        QuestionAgent() if lab.local_llm else FixtureQuestionAgent(),lab.planner,
        timeout=float(os.getenv('QUESTION_TIMEOUT_SECONDS','60')),
        max_active=int(os.getenv('QUESTION_MAX_ACTIVE','4')))
