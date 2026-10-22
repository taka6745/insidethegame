"""Native Microsoft Agent Framework question agent with allowlisted function tools."""
import json
import re
import httpx
from agent_framework import Agent, tool
from openai import AsyncOpenAI
from backend.adapters.llm import LocalJsonModel, chat_client, chat_options
from backend.models.actions import ActionType
from backend.models.questions import QuestionDraft
from .question_instructions import QUESTION_INSTRUCTIONS
from .question_contracts import QuestionDecision
from .question_intent import QuestionIntentRouter
from .football_reference import load_reference
from .replay import ReplayAgent
from .measurement_support import measurement_support
from backend.services.question_answers import SENT_OFF

EXPLAIN = re.compile(r'\b(?:why|how|explain|describe|what happened)\b', re.I)

class QuestionAgent:
    mode = 'local'
    def __init__(self, settings=None, *, router=None, replay=None):
        self.settings = settings or LocalJsonModel.from_env(name='match_question')
        self.router = router or QuestionIntentRouter(self.settings)
        self.replay = replay or ReplayAgent(self.settings)

    async def answer(self, prompt, context, tools):
        tools.original_prompt = prompt
        intent = await self.router.route(prompt, context)
        if (bounded := match_choice(intent, context)) is not None:
            return bounded
        if intent.route == "match" and SENT_OFF.search(prompt) and not EXPLAIN.search(prompt):
            # Who was sent off is read from MA3 cards by code, not written as model prose.
            intent = intent.model_copy(update={"route": "statistic"})
        if intent.route == "statistic":
            # The resolver invokes the existing planner with the original dialogue.
            # No answer model sees actions it could silently count itself.
            return QuestionDraft(answer_kind="statistic", status="answer",
                                 text="Checking the requested statistic.")
        if intent.route == "clarification":
            return QuestionDraft(answer_kind="match", status="clarification", text=intent.question,
                                 clarification={"question": intent.question, "options": intent.options,
                                                "allow_free_text": intent.allow_free_text})
        if intent.route == "replay":
            return replay_draft(await self.replay.plan(prompt, context, tools.replay))
        if intent.route == "unsupported":
            return QuestionDraft(answer_kind="match", status="unsupported",
                                 text="Sorry, I can only answer questions about football and this match.")
        context = {**context, "request_kind": intent.route,
                   "measurement_support": measurement_support(context.get('data_reference', {}))}
        if intent.route == "football":
            context["football_reference"] = load_reference()
        @tool(max_invocations=6)
        async def read_standard_stats(ids: list[str] | None = None) -> dict:
            """Read ETL-computed whole-match stats. Optional exact IDs from context catalogue."""
            return await tools.standard(ids)

        @tool(max_invocations=6)
        async def search_actions(start: int | None = None, end: int | None = None,
                                 action_type: ActionType | None = None, player_id: str | None = None,
                                 team_id: str | None = None, offset: int = 0, period: int | None = None,
                                 end_inclusive: bool = False) -> dict:
            """Read individual observed SPADL actions as evidence, 100/page. Whole-match seconds [start,end); set end_inclusive=true when the requested final timestamp is included. Never aggregate this list. Period 1/2 selects first/second half."""
            return await tools.actions(start, end, action_type, player_id, offset, period, team_id, end_inclusive=end_inclusive)

        @tool(max_invocations=2)
        async def read_cards() -> dict:
            """Cards shown so far (yellow, second_yellow, red), with player, team and minute. Cards are not SPADL actions."""
            return await tools.cards()

        @tool(max_invocations=4)
        async def lookup_spadl(term: str) -> dict:
            """The SPADL contract for one term (action type, result, body part, zone, catalogue stat id or kind, field): definition, Opta source, catalogue stats using it, and a goal example."""
            return tools.lookup(term)

        @tool(max_invocations=6)
        async def read_recaps(ids: list[str] | None = None, start: int | None = None,
                              end: int | None = None, tier: str | None = None, offset: int = 0) -> dict:
            """Read archived neutral recap children or intervals [start,end) seconds. Tiers minute, five-minute, earlier. Archived children remain readable."""
            return await tools.recaps(ids, start, end, tier, offset)

        @tool(max_invocations=2)
        async def prepare_stat(request: str) -> dict:
            """Calculate a new metric once, using the existing validated rule workflow. Give a complete request with prior constraints resolved. Does not track yet."""
            return await tools.prepare(request)

        cfg = self.settings
        async with httpx.AsyncClient(timeout=min(cfg.timeout, 60), transport=cfg.transport) as http:
            async with AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key or 'local-development',
                                   http_client=http, max_retries=0) as client:
                chat = chat_client(cfg.model, client)
                chat.function_invocation_configuration.update(max_iterations=7, max_function_calls=6, max_duration_seconds=55)
                agent = Agent(name='match_question', client=chat, instructions=QUESTION_INSTRUCTIONS,
                              tools=[read_standard_stats, search_actions, read_cards, read_recaps, prepare_stat, lookup_spadl],
                              default_options={**chat_options(1600),'allow_multiple_tool_calls':False})
                response = await agent.run(json.dumps({'question':prompt, **context}),
                                           options={'response_format':QuestionDecision})
        if response.finish_reason == 'length':
            raise ValueError('Truncated question answer')
        return QuestionDecision.model_validate_json(response.text).draft(tools)


def match_choice(intent, context):
    """A data request about several other live matches, none named: ask which, offering only the real matches
    (their team names, which the service resolves on the next turn). None otherwise."""
    others = {row['match_id']: row for row in context.get('live_matches', []) if not row['this_match']}
    chosen = [others[i] for i in dict.fromkeys(intent.matches) if i in others]
    if len(chosen) < 2 or intent.route not in ('statistic', 'replay', 'clarification'):
        return None
    options = [' v '.join(row['teams']) for row in chosen][:5]
    return QuestionDraft(answer_kind='match', status='clarification', text='Which match?',
                         clarification={'question': 'Which match?', 'options': options, 'allow_free_text': True})


def replay_draft(decision):
    """The specialist's evidence plan becomes a reply; clip seconds are cut by the service."""
    return QuestionDraft(answer_kind='replay', status=decision.status, text=decision.text,
                         replay_items=[item.model_dump() for item in decision.items],
                         refine_offer=decision.refine_offer)
