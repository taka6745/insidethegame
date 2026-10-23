"""Answers are computed at the viewer's shown snapshot, never past it, even when the backend is ahead."""
from uuid import uuid4

import pytest

from backend.models.questions import QuestionDraft
from harness import MATCH, Running
from support import path, start


class Citing:
    """Lists every SPADL action the tools expose and cites the newest one."""
    mode = 'fixture'

    def __init__(self):
        self.seen = []

    async def answer(self, prompt, context, tools):
        items = (await tools.actions())['items']
        final = {a.id: a.final_seq for a in tools.payload.actions}
        self.seen.append((context['snapshot']['seq'], [final[item['id']] for item in items]))
        return QuestionDraft(answer_kind='match', status='answer', text='The latest action.',
                             evidence_ids=[items[-1]['evidence_id']] if items else [])


def ask(client, token, seq=None, route='product'):
    body = {'prompt': 'what just happened', 'request_id': str(uuid4()), **({} if seq is None else {'seq': seq})}
    url = (path(token) + '/messages' if route == 'product' else f'/lab/matches/{MATCH}/chat/{token}/messages')
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('route', ['product', 'lab'])
def test_answers_never_cite_actions_after_the_viewers_seq(store, route):
    agent = Citing()
    with Running(store, agent=agent) as run:
        run.send(20)
        token = start(run.client)['session_token'] if route == 'product' else run.client.post(
            f'/lab/matches/{MATCH}/chat/sessions', json={'profile_id': 'riverton-analytical'}).json()['session_token']
        for shown in (8, 2):
            reply = ask(run.client, token, shown, route)
            assert reply['snapshot']['seq'] == shown and reply['snapshot']['id'] == f'{MATCH}:{shown}'
            seq, sequences = agent.seen[-1]
            assert seq == shown and sequences and max(sequences) <= shown
            later = {f"action:a{a['actionId']}" for a in run.upstream.matches[MATCH].actions() if shown < a['finalSeq'] <= 20}
            assert later
            assert reply['evidence'] and not {item['id'] for item in reply['evidence']} & later
        # A seq ahead of what ETL and the backend committed is capped at the newest snapshot.
        assert ask(run.client, token, 500, route)['snapshot']['seq'] == 20
        assert ask(run.client, token, None, route)['snapshot']['seq'] == 20


def test_unconfirmed_actions_stay_unreachable_whatever_seq_the_client_sends(store):
    agent = Citing()
    with Running(store, agent=agent) as run:
        run.send(5)
        run.send(10, commit=False)  # Received here, not yet committed by ETL.
        token = start(run.client)['session_token']
        assert ask(run.client, token, 15)['snapshot']['seq'] == 5
        assert max(agent.seen[-1][1]) <= 5


@pytest.mark.parametrize('seq', [-1, 'eight', 100_001])
def test_invalid_seq_is_refused(store, seq):
    with Running(store, agent=Citing()) as run:
        token = start(run.client)['session_token']
        response = run.client.post(path(token) + '/messages',
                                   json={'prompt': 'x', 'request_id': str(uuid4()), 'seq': seq})
        assert response.status_code == 422
