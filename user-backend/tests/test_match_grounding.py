"""Match prose requires observed evidence; general football explanations do not."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.agents.question_contracts import QuestionDecision


def match_decision(evidence_ids):
    return QuestionDecision.model_validate({'decision': {
        'route': 'match', 'text': 'United took the lead.', 'evidence_ids': evidence_ids,
    }})


def test_match_answer_without_evidence_fails_closed():
    with pytest.raises(ValidationError):
        match_decision([])


def test_match_answer_cannot_cite_an_unobserved_event():
    tools = SimpleNamespace(evidence={'event:observed:1': {}})
    with pytest.raises(ValueError, match='unavailable evidence'):
        match_decision(['event:future:1']).draft(tools)


def test_match_answer_accepts_current_question_evidence():
    tools = SimpleNamespace(evidence={'event:observed:1': {}})
    draft = match_decision(['event:observed:1']).draft(tools)
    assert draft.status == 'answer'
    assert draft.evidence_ids == ['event:observed:1']


def test_general_football_does_not_require_match_evidence():
    draft = QuestionDecision.model_validate({'decision': {
        'route': 'football', 'text': 'A corner restarts play from the corner area.',
    }}).draft(SimpleNamespace(evidence={}))
    assert draft.answer_kind == 'football'
    assert draft.evidence_ids == []
