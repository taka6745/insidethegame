"""One yes/no question to a decision model: Microsoft-Decision-1 on Azure AI Foundry (SystemOne API, the engine's
decisions/systemone envelope), else the local JSON model constrained to yes/no. Used for the "Follow this story?"
offer (PLAN.md §10.2 D5b). DECISION_BASE_URL, DECISION_API_KEY, DECISION_MODEL, DECISION_PATH, DECISION_AUTH and
DECISION_MODEL_FIELD as the engine reads them; values are never logged."""
import asyncio
import json
import os
import time

import httpx

YES_NO = {'type': 'json_schema', 'json_schema': {'name': 'decision', 'strict': True, 'schema': {
    'type': 'object', 'additionalProperties': False, 'required': ['answer', 'confidence'],
    'properties': {'answer': {'type': 'string', 'enum': ['yes', 'no']}, 'confidence': {'type': 'number'}}}}}
SYSTEM = ('You are a classifier. Read the state and answer the question yes or no with your confidence (0 to 1) '
          'that the answer is right. Reply with only the JSON object the schema describes.')


class Window:
    """At most `per_minute` calls in any 60 seconds; a call over the limit is refused, never queued."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.stamps = clock, []

    def take(self, per_minute):
        now = self.clock()
        self.stamps = [t for t in self.stamps if now - t < 60.0]
        if len(self.stamps) >= per_minute:
            return False
        self.stamps.append(now)
        return True


class SystemOneYesNo:
    def __init__(self, base_url, api_key='', model='', path='/providers/microsoft/v1/systemone', auth='api-key',
                 model_field='model', transport=None):
        headers = {'Content-Type': 'application/json'}
        if auth == 'api-key':
            headers['api-key'] = api_key
        elif auth == 'bearer':
            headers['Authorization'] = f'Bearer {api_key}'
        self.url = base_url.rstrip('/') + '/' + path.lstrip('/')
        self.model, self.model_field, self.headers, self.transport = model, model_field, headers, transport

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        if not env.get('DECISION_BASE_URL'):
            return None
        extra = {k: env[f'DECISION_{k.upper()}'] for k in ('path', 'auth', 'model_field')
                 if env.get(f'DECISION_{k.upper()}') is not None}
        return cls(env['DECISION_BASE_URL'], env.get('DECISION_API_KEY', ''), env.get('DECISION_MODEL', ''), **extra)

    async def probability(self, state, instructions, true, false, timeout):
        body = {'state': state, 'questions': {'q': {'type': 'noul', 'instructions': instructions,
                                                    'criteria': {'true': true, 'false': false}}}}
        if self.model_field:
            body = {self.model_field: self.model, **body}
        async with httpx.AsyncClient(timeout=timeout, headers=self.headers, transport=self.transport) as http:
            response = await http.post(self.url, json=body)
        response.raise_for_status()
        value = float(((response.json().get('answers') or {}).get('q') or {})['noul'])
        if not 0 <= value <= 1:
            raise ValueError('probability outside 0..1')
        return value


class ModelYesNo:
    """The local fallback: adapters/llm.JsonModel answering yes or no with a confidence."""

    def __init__(self, model):
        self.model = model

    async def probability(self, state, instructions, true, false, timeout):
        reply = await asyncio.wait_for(self.model.complete(SYSTEM, {
            'state': state, 'question': instructions, 'yes means': true, 'no means': false}, response_schema=YES_NO),
            timeout)
        confidence = float(reply['confidence'])
        if reply.get('answer') not in ('yes', 'no') or not 0 <= confidence <= 1:
            raise ValueError('invalid yes/no reply')
        return confidence if reply['answer'] == 'yes' else 1.0 - confidence


def yes_no_from_env(fallback_model=None):
    """Decision-1 when DECISION_BASE_URL is set, else the local JSON model, else None (no offers)."""
    return SystemOneYesNo.from_env() or (ModelYesNo(fallback_model) if fallback_model else None)


def state(prompt, answer):
    return json.dumps({'question': prompt, 'answer': answer})
