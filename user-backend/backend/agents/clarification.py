"""Cheap, conservative checks for references that have no conversation antecedent."""
import re
import unicodedata

from backend.agents.models import Clarification, GoalDecision


def normalize(text: str) -> str:
    return ''.join(char for char in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(char)).replace('’', "'")


def unresolved_player(prompt: str, context: dict) -> GoalDecision | None:
    """Do not guess a player merely because only one keeper is in the catalogue."""
    if context.get('conversation'):
        return None
    text = normalize(prompt)
    reference = re.search(r"\b(?:his|her|(?:that|this) player's?)\b", text)
    if reference is None:
        return None
    antecedents = set()
    for player in context.get('players', []):
        for value in (player['id'], player.get('name', '')):
            if value and re.search(r'\b' + re.escape(normalize(value)) + r'\b', text[:reference.start()]):
                antecedents.add(player['id'])
    if len(antecedents) == 1:
        return None
    return GoalDecision(status='clarification', clarification=Clarification(
        question='Which player in this match do you mean?', missing_fields=['player'],
        options=[str(player.get("name") or player["id"])[:200] for player in context.get("players", [])][:5]))
