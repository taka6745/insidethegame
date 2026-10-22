"""Explicit development double. Does not masquerade as a general language model."""
from backend.models.questions import QuestionDraft
from backend.agents.question import replay_draft
from .replay_agent import FixtureReplayAgent, is_replay

class FixtureQuestionAgent:
    mode = 'fixture'
    async def answer(self, prompt, context, tools):
        if is_replay(prompt):
            return replay_draft(await FixtureReplayAgent().plan(prompt, context, tools.replay))
        text = prompt.lower().strip().rstrip('?')
        if text in ('what is offside', "what's offside", 'explain offside'):
            return QuestionDraft(answer_kind='football',status='answer', text='A player can be offside when they become involved in play from an offside position as a teammate plays the ball. Being in that position alone is not an offence.')
        if text in ('how is the match going', 'how is the game going', 'match recap'):
            blocks = context['compact']['blocks']
            if blocks:
                return QuestionDraft(answer_kind='match',status='answer',text=blocks[-1]['summary'][:1500],evidence_ids=[blocks[-1]['id']])
            return QuestionDraft(answer_kind='match',status='answer',text='There is not a completed minute of recorded play yet.')
        for row in tools.stats:
            if text == f"how many {row['label'].lower()}" or text == row['label'].lower():
                return QuestionDraft(answer_kind='statistic',status='answer',standard_stat_id=row['id'],text=f"{row['label']}: {row['value']}.",evidence_ids=['stat:'+row['id']])
        if text in ('headers', 'how many headers'):
            return QuestionDraft(answer_kind='match',status='clarification',text='Do you mean headed passes, headed shots including goals, or all recorded headed contacts?')
        result = await tools.prepare(prompt)
        if result['status'] == 'ready':
            return QuestionDraft(answer_kind='statistic',status='answer',selected_offer_id=result['offer_id'],text=f"{result['label']}: {result['value']}.",evidence_ids=[result['evidence_id']])
        if result['status'] == 'ranking':
            return QuestionDraft(answer_kind='statistic',status='answer',statistic_request=prompt,text=result['text'])
        if result['status'] == 'clarification':
            return QuestionDraft(answer_kind='match',status='clarification',text=result['message'])
        if result['status'] == 'reuse' and result.get('stat'):
            row = result['stat']
            return QuestionDraft(answer_kind='statistic',status='answer',standard_stat_id=row['id'],text=f"{row['label']}: {row['value']}.",evidence_ids=[result['evidence_id']])
        return QuestionDraft(answer_kind='match',status='unsupported',text='Sorry, I cannot answer that in fixture mode. Try a listed request or enable the local model.')


class ScriptedModel:
    """Golden-set double: the model's route and goal decision are scripted per case (a correct
    one, or one a model actually returned), so the real QuestionAgent, planner, ETL-row answers
    and rule engine run deterministically. It never writes prose."""
    script = None

    async def route(self, prompt, context):
        from backend.agents.question_intent import QuestionIntent
        return QuestionIntent.model_validate({'route': self.script['route'], **self.script.get('intent', {})})

    async def complete(self, system, payload, **unused):
        """The goal model's JSON (GoalAgent validates it as it would a model reply)."""
        return self.script['decision']
