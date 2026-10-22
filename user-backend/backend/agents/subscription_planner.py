"""The follow chat's planner: one model call turns the viewer's message into a PlannerDraft (models/subscriptions).

The template is the active `subscription-planner` prompt; teams, players and storylines are listed so the model
can name them, but it never supplies ids: services/subscriptions.resolve maps names to ids by rule."""
import re

from backend.models.subscriptions import PLANNER_SCHEMA, PlannerDraft

PLACEHOLDER = re.compile(r'\{([a-z_]+)\}')


def render(template, variables):
    return PLACEHOLDER.sub(lambda m: str(variables.get(m.group(1), m.group(0))), template)


class SubscriptionPlanner:
    def __init__(self, model, prompts):
        self.model, self.prompts = model, prompts  # adapters/llm.JsonModel, services/prompts.PromptService

    async def plan(self, message, *, teams, players, storylines, follow, turns, live_matches=()):
        """`turns`: the recent follow-chat turns to show (limits.planner_context_turns, chosen by the caller)."""
        team_names = {t['id']: t['name'] for t in teams}
        variables = {
            'teams': '\n'.join(f"- {t['name']} ({', '.join([t.get('code') or t['id'], *(t.get('known_names') or ())])})"
                               for t in teams) or '(none)',
            'players': '\n'.join(f"- {p['name']} ({team_names.get(p['team_id'], p['team_id'])})" for p in players) or '(none)',
            'storylines': '\n'.join(f"- {s['label']} ({team_names.get(s['team_id'], 'both teams')}, {s['status']})"
                                    for s in storylines) or '(none yet)',
            'current_follow': follow['label'] if follow else '(none)',
            'live_matches': '\n'.join(f"- {' v '.join(m['teams'])}" + (f" ({m['minute']})" if m.get('minute') else '')
                                       + (' (this match)' if m.get('this_match') else '') for m in live_matches)
                            or '(this match only)',
            'conversation': '\n'.join(f"Viewer: {t['prompt']}\nYou: {(t['reply'] or {}).get('text', '')}"
                                      for t in turns) or '(none)'}
        system = render(await self.prompts.template('subscription-planner'), variables)
        return PlannerDraft.model_validate(await self.model.complete(system, {'message': message},
                                                                     response_schema=PLANNER_SCHEMA))
