"""Opt-in real-model conversation smoke check; qualitative answers need human review."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx


def close(actual, expected):
    return isinstance(actual, (int, float)) and abs(actual - expected) < 0.01


def check(case, body, suite):
    """Deterministic checks only; prose still needs the saved review notes."""
    offers = body.get('offers', [])
    checks = {'snapshot': body.get('snapshot', {}).get('recording_hash') == suite['recording_hash'],
              'status': body.get('status') == case.get('status', 'answer')}
    if 'answer_kind' in case:
        checks['answer_kind'] = body.get('answer_kind') == case['answer_kind']
    if 'offer_value' in case:
        checks['offer'] = len(offers) == 1 and 'rule' in offers[0] and close(offers[0]['value'], case['offer_value'])
    if 'standard_stat_id' in case:
        checks['standard_source'] = (
            body.get('standard_stat_id') == case['standard_stat_id']
            and [[o.get('standard_stat_id'), o.get('value')] for o in offers] == case['offers']
            and all(o.get('kind') == 'standard' and 'rule' not in o for o in offers))
    if 'text_includes' in case:
        text = (body.get('text') or '').lower()
        checks['named_reason'] = all(word in text for word in case['text_includes'])
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:18020/api')
    parser.add_argument('--profile', default='chelsea-analytical')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new file to preserve earlier evidence.')
    suite = json.loads(Path(__file__).with_name('question_cases.json').read_text())
    results = {'started_at': datetime.now(timezone.utc).isoformat(), 'cases': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url, timeout=90) as client:
        state = client.get('/state').raise_for_status().json()
        if state['status'] != 'finished' or state['match_id'] != suite['match_id'] or state['position'] != state['total']:
            parser.error('Finish the shipped Chelsea–United recording first. This runner never resets/replays it.')
        session = client.post('/chat/sessions', json={'profile_id': args.profile}).raise_for_status().json()
        if session['mode'] != 'local':
            parser.error('This evaluation requires the real local-model mode, not fixture answers.')
        if session['turns']:
            parser.error('Use a fresh run/conversation so earlier answers cannot contaminate this evaluation.')
        token = session['session_token']
        calculation_ids = {row['id'] for row in state['calculations']}
        args.output.write_text(json.dumps(results, indent=2)+'\n')
        for case in suite['cases']:
            started = time.monotonic()
            try:
                response = client.post(f'/chat/{token}/messages', json={'prompt': case['prompt'], 'request_id': str(uuid4())})
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError('Expected an object')
                current = client.get('/state').raise_for_status().json()
            except (httpx.HTTPError, ValueError) as exc:
                results['cases'].append({**case, 'seconds': round(time.monotonic()-started, 2),
                                         'checks': {'request_completed': False}, 'error_type': type(exc).__name__})
                args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False)+'\n')
                raise SystemExit('Request failed; failed attempt and earlier evidence saved.') from None
            checks = {'http_ok': response.status_code == 200, **check(case, body, suite),
                      'same_run': current['run_id'] == state['run_id'],
                      'no_tracking': {row['id'] for row in current['calculations']} == calculation_ids}
            results['cases'].append({**case, 'seconds': round(time.monotonic()-started, 2),
                                     'checks': checks, 'reply': body})
            # Never give review notes or expected values to the model.
            args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False)+'\n')
            print(case['id'], 'checks passed' if all(checks.values()) else 'CHECK FAILED',
                  results['cases'][-1]['seconds'], body.get('text'), flush=True)
            if not checks['snapshot']:
                raise SystemExit('Wrong recording/run data; stop and inspect saved evidence.')
    print('Review EVERY answer and rule against the saved review notes. Automatic checks are not an accuracy score.')
    if not all(all(row['checks'].values()) for row in results['cases']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
