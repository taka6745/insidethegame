"""Deterministic stand-in decision model for tests and offline runs. No model calls.

`answers` maps a question key to a fixed probability (noul), option (choice) or level index (score); a key
not listed gets `rule(key, question, state)` when given (None: fall through), else `default` (a probability or
level; a choice falls back to its first option). Every call is kept in `calls` as (state, questions).
"""
from narrative_engine.decisions import Answer, Choice, Decisions, Noul


class FakeDecisions:
    def __init__(self, answers=None, default=0.0, rule=None):
        self.answers, self.default, self.rule, self.calls = dict(answers or {}), default, rule, []

    async def decide(self, state, questions):
        self.calls.append((state, dict(questions)))
        out = {}
        for key, question in questions.items():
            value = self.answers.get(key)
            if value is None and self.rule is not None:
                value = self.rule(key, question, state)
            value = self.default if value is None else value
            if isinstance(question, Noul):
                out[key] = Answer("noul", probability=float(value))
            elif isinstance(question, Choice):
                choice = value if value in question.options else next(iter(question.options))
                out[key] = Answer("choice", choice=choice, confidence=1.0, probabilities={choice: 1.0})
            else:
                level = min(max(int(value), 0), len(question.levels) - 1)
                out[key] = Answer("score", score=float(level), confidence=1.0, probabilities={str(level): 1.0})
        return Decisions(out, "fake", None)

    async def aclose(self):
        pass
