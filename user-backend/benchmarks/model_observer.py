"""Benchmark-only HTTP observation. Never retain URLs, headers or response text."""
import asyncio
import hashlib
import json
import time

import httpx


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def response_metadata(content):
    """Read standard JSON or SSE metadata without persisting generated content."""
    try:
        payloads = [json.loads(content)]
    except (ValueError, UnicodeError):
        payloads = []
        for line in content.decode('utf-8', errors='replace').splitlines():
            if line.startswith('data: ') and line[6:] != '[DONE]':
                try:
                    payloads.append(json.loads(line[6:]))
                except ValueError:
                    continue
    models, usage = set(), {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        model = payload.get('model')
        if isinstance(model, str) and len(model) <= 200 and '://' not in model:
            models.add(model)
        raw_usage = payload.get('usage') or {}
        if isinstance(raw_usage, dict):
            for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                value = raw_usage.get(key)
                if type(value) is int and value >= 0:
                    usage[key] = value
            if isinstance(raw_usage.get('estimated'), bool):
                usage['estimated'] = raw_usage['estimated']
    return sorted(models), usage


class ModelObserver(httpx.AsyncBaseTransport):
    def __init__(self, *, transport_factory=None):
        self.transport_factory = transport_factory or (lambda: httpx.AsyncHTTPTransport(retries=0))
        self.calls = []

    async def handle_async_request(self, request):
        start = time.perf_counter()
        record = {'http_status': None, 'actual_models': [], 'tokens': {}, 'status': 'pending'}
        self.calls.append(record)
        request.headers['Cache-Control'] = 'no-cache'
        try:
            body = await request.aread()
            record['request_bytes'] = len(body)
            record['request_sha256'] = hashlib.sha256(body).hexdigest()
            try:
                payload = json.loads(body)
                record['requested_model'] = payload.get('model')
                response_format = payload.get('response_format') or {}
                record['response_format'] = response_format.get('type', 'prompt')
                schema_spec = response_format.get('json_schema') or {}
                if isinstance(schema_spec, dict) and 'schema' in schema_spec:
                    record['wire_schema_sha256'] = digest(schema_spec['schema'])
                    record['strict_requested'] = schema_spec.get('strict') is True
                record['system_prompt_sha256'] = digest([
                    row.get('content') for row in payload.get('messages', []) if row.get('role') in {'system', 'developer'}])
            except (ValueError, AttributeError):
                pass
            # LocalJsonModel creates/closes a client per call. A fresh inner
            # transport prevents a schema-repair call reusing a closed pool.
            async with self.transport_factory() as transport:
                response = await transport.handle_async_request(request)
                content = await response.aread()
            record['http_status'] = response.status_code
            record['actual_models'], record['tokens'] = response_metadata(content)
            record['status'] = 'ok' if 200 <= response.status_code < 300 else 'http_error'
            return response
        except asyncio.CancelledError:
            record['status'] = 'cancelled'
            raise
        except Exception as exc:
            record['status'] = 'transport_error'
            record['error_type'] = type(exc).__name__  # Never an exception message.
            raise
        finally:
            record['seconds'] = round(time.perf_counter() - start, 3)


def pin_verification(calls, expected_models):
    successful = [call for call in calls if call['status'] == 'ok']
    actual = sorted({model for call in successful for model in call['actual_models']})
    if not calls:
        return {'pin_verified': False, 'pin_reason': 'model_not_invoked', 'actual_models': actual}
    if not successful:
        return {'pin_verified': False, 'pin_reason': 'no_successful_model_response', 'actual_models': actual}
    if any(model not in expected_models for model in actual):
        return {'pin_verified': False, 'pin_reason': 'unexpected_model_substitution', 'actual_models': actual}
    if any(not call['actual_models'] for call in successful):
        return {'pin_verified': False, 'pin_reason': 'missing_returned_model_identity', 'actual_models': actual}
    return {'pin_verified': True, 'pin_reason': 'verified', 'actual_models': actual}
