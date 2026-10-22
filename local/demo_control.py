"""Demo control: the operator between the simulated provider and our services. Not a product service.

CLI (local): `purge` every match from every owner; `start [fixture…]` purges, then starts feed runs from 00:00.
HTTP (`serve`, behind the frontend's public /demo-api/): start the configured demo, cancel it, read its state.
Purge order follows local/contracts.md §5: feed, ETL, engine, backend. Configuration stays."""
import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

FEED = os.environ.get('DEMO_FEED_URL', 'http://feed:8000')
OWNERS = (('feed', FEED + '/admin/matches/purge', None),
          ('etl', os.environ.get('ETL_ADMIN_URL', 'http://etl-stream:8000') + '/admin/matches/purge',
           os.environ.get('ETL_ADMIN_TOKEN')),
          ('engine', os.environ.get('ENGINE_ADMIN_URL', 'http://narrative-live:8000') + '/admin/matches/purge',
           os.environ.get('ENGINE_ADMIN_TOKEN')),
          ('backend', os.environ.get('BACKEND_URL', 'http://backend:8000') + '/admin/matches/purge', None))
PURGE_TIMEOUT = 300  # Seconds; a purge waits for the stream's current batch, slow under load.
PURGE_RETRIES, PURGE_RETRY_SECONDS = 10, 2  # 503 means retry; purge is idempotent.
CHECK_TIMEOUT = 3  # Seconds per readiness probe.
WAKE_TIMEOUT = 60  # Seconds a wake-up call waits for an app scaled to zero.
SEED_ROOT = Path(os.environ.get('DEMO_SEED_ROOT', '/seeds'))  # seeds/{seed_id}/: manifest + one file per owner
SEED_OWNERS = ('etl', 'engine', 'backend')  # restore_runs: the ETL alongside the backend, then the engine
RELEASE_LEAD = 5  # Seconds from the last restore to the first run's clock reading the start point.
CAPTURE_POLL, CAPTURE_TIMEOUT = 5, 1800  # Seconds: a held run's owners must settle before a capture.
SEED_FORMAT = 2  # manifest layout; 2 adds each owner's schema fingerprint and the source run id


class SeedStale(RuntimeError):
    """A seed this pipeline cannot restore (another format or owner schema, or another start point)."""


def owner_url(name, path):
    url, token = next((u, t) for n, u, t in OWNERS if n == name)
    return url.removesuffix('/admin/matches/purge') + path, ({'Authorization': f'Bearer {token}'} if token else {})


def owner_call(http, name, path, body):
    url, headers = owner_url(name, path)
    response = http.post(url, json=body, headers=headers) if name != 'etl' or path.endswith('restore') else \
        http.get(url + f"?match_id={body['match_id']}", headers=headers)
    if response.status_code >= 400:
        error = SeedStale if response.status_code == 409 and path.endswith('restore') else RuntimeError
        raise error(f'{name} {path}: {response.status_code} {response.text[:300]}')
    return response.json()


def export_parts(http, match_id):
    """Each owner's rows for one match: {owner: payload}, plus `schemas` {owner: schema fingerprint}."""
    etl = owner_call(http, 'etl', '/admin/matches/export', {'match_id': match_id})
    engine = owner_call(http, 'engine', '/admin/matches/export', {'match_id': match_id})
    backend = owner_call(http, 'backend', '/admin/matches/export', {'match_id': match_id})
    return {'etl': etl['tables'], 'engine': engine['containers'], 'backend': backend['tables'],
            'schemas': {'etl': etl['schema'], 'engine': engine['schema'], 'backend': backend['schema']}}


def settled(parts, run):
    """A held run is captured once every owner has caught up with what it sent: the ETL's watermark is the run's
    seq, the engine has summarised the last minute with nothing queued, the backend has every event and every
    engine narrative."""
    seq = run['seq']
    progress = parts['etl'].get('matchProgress') or [{}]
    events = parts['etl'].get('canonicalEvents', [])
    if not seq or progress[0].get('seq') != seq or len(events) != seq:
        return False
    last = max((e['periodId'], int(e['matchTimeSeconds']) // 60) for e in events)
    checkpoint = (parts['engine'].get('checkpoints') or [{}])[0]
    if checkpoint.get('closedThrough') != f'{last[0]}-{last[1]:03d}' or checkpoint.get('pending'):
        return False
    if checkpoint.get('lastSummarised') != checkpoint.get('closedThrough'):
        return False
    backend = parts['backend']
    return (len(backend.get('received_events', [])) == seq and
            len(backend.get('engine_narratives', [])) == len(parts['engine'].get('narratives', [])))


def capture(http, point, log=print, timeout=CAPTURE_TIMEOUT):
    """Snapshot every held run (one per fixture) at `point` into SEED_ROOT/{seed_id}, then name the seed on
    the feed's start point. Nothing past the point exists: the feed never sent it (`hold_point`)."""
    deadline = time.monotonic() + timeout
    while True:
        runs = [r for r in http.get(FEED + '/runs').raise_for_status().json()
                if r['status'] != 'finished' and r.get('hold_seconds') is not None]
        held = [r for r in runs if r['video_seconds'] >= r['hold_seconds'] - 0.01]
        parts = {r['match_id']: export_parts(http, r['match_id']) for r in held} if held and len(held) == len(runs) else {}
        waiting = [r['match_id'] for r in runs if r['match_id'] not in parts or not settled(parts[r['match_id']], r)]
        if runs and not waiting:
            break
        if time.monotonic() > deadline:
            raise SystemExit(f'Owners did not settle for {", ".join(waiting) or "any held run"}')
        log(f'Waiting for {", ".join(waiting) or "held runs"}')
        time.sleep(CAPTURE_POLL)
    seed_id = f"{point}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    root = SEED_ROOT / seed_id
    fixtures = {}
    for run in runs:
        for owner in SEED_OWNERS:
            (root / owner).mkdir(parents=True, exist_ok=True)
            (root / owner / f"{run['fixture']}.json").write_text(json.dumps(parts[run['match_id']][owner]))
        fixtures[run['fixture']] = {'source_match_id': run['match_id'], 'source_run_id': run['run_id'],
                                    'seq': run['seq'], 'video_seconds': run['hold_seconds']}
    schemas = parts[runs[0]['match_id']]['schemas']
    if any(parts[r['match_id']]['schemas'] != schemas for r in runs):
        raise SystemExit('Owners reported different schemas while exporting; capture again')
    (root / 'manifest.json').write_text(json.dumps({'format': SEED_FORMAT, 'seed_id': seed_id, 'point': point,
                                                    'schemas': schemas, 'fixtures': fixtures,
                                                    'created_at': datetime.now(timezone.utc).isoformat()}, indent=2))
    settings = http.get(FEED + '/demo').raise_for_status().json()
    points = [{**p, 'seed': seed_id} if p['id'] == point else p for p in settings['start_points']]
    body = {k: v for k, v in settings.items() if k not in ('start_points', 'revision')}
    http.put(FEED + '/demo', json={**body, 'start_points': points, 'expected_revision': settings['revision']}
             ).raise_for_status()
    for run in runs:  # the recording is done: its runs leave every owner
        purge(http, {'match_id': run['match_id']}, log=lambda _: None)
    log(f'Seed {seed_id}: {fixtures}')
    return seed_id


def seed_manifest(seed_id, fixtures):
    """The seed's manifest, or SeedStale when it is missing, of another format or lacks a fixture. Each owner
    checks its own schema fingerprint at restore."""
    try:
        manifest = json.loads((SEED_ROOT / seed_id / 'manifest.json').read_text())
    except (OSError, ValueError) as exc:
        raise SeedStale(f'seed {seed_id} is missing or unreadable') from exc
    if manifest.get('format') != SEED_FORMAT or set(manifest.get('schemas') or ()) != set(SEED_OWNERS):
        raise SeedStale(f"seed {seed_id} has format {manifest.get('format')}; this pipeline needs {SEED_FORMAT}")
    missing = sorted(set(fixtures) - set(manifest.get('fixtures') or {}))
    if missing:
        raise SeedStale(f"seed {seed_id} has no {', '.join(missing)}")
    return manifest


def seed_ready(seed_id, fixtures):
    """Whether a start point's seed exists and fits this pipeline (a stale seed reads as not recorded yet)."""
    try:
        return bool(seed_id) and bool(seed_manifest(seed_id, fixtures))
    except SeedStale:
        return False


def seed_parts(seed_id, manifest, fixture, match_id, run_id):
    """One fixture's seed, rewritten for a new run: its matchId and runId everywhere, and its MA1 as sent now."""
    root, source = SEED_ROOT / seed_id, manifest['fixtures'][fixture]

    def moved(text):
        return text.replace(source['source_match_id'], match_id).replace(source['source_run_id'], run_id)

    parts = {owner: json.loads(moved((root / owner / f'{fixture}.json').read_text())) for owner in SEED_OWNERS}
    now = datetime.now(timezone.utc).isoformat()
    for row in parts['etl'].get('matches', []):  # the run's MA1 counts as sent now (purge-all cut-offs)
        payload = json.loads(row['payload'])
        row['payload'] = json.dumps({**payload, 'timeStamp': now.replace('+00:00', 'Z')})
    for row in parts['backend'].get('received_matches', []):
        row.update(run_id=run_id, sent_at=now)
    return parts, source['seq']


def main_first(runs, main):
    return sorted(runs, key=lambda run: run['fixture'] != main)  # stable: the rest keep their order


def restore_runs(http, seed_id, runs, stagger, log=print):
    """Restore every owner for each run waiting on the seed, then release the runs, staggered in the order given
    (the main game first: it stays furthest along). A failure purges the runs everywhere; SeedStale when the
    seed no longer fits (record it again)."""
    try:
        manifest = seed_manifest(seed_id, [run['fixture'] for run in runs])
        schemas = manifest['schemas']

        def restore_one(run):  # owners in this order; the runs' matches are independent
            began, took = time.monotonic(), {}
            parts, seq = seed_parts(seed_id, manifest, run['fixture'], run['match_id'], run['run_id'])
            took['read'] = time.monotonic() - began
            if run.get('seq') != seq:  # the feed resumes after this seq; any other would leave a gap or repeat
                raise SeedStale(f"the feed resumes {run['fixture']} after seq {run.get('seq')}, the seed holds {seq}")
            def call(owner, key):
                mark = time.monotonic()
                owner_call(http, owner, '/admin/matches/restore', {'match_id': run['match_id'], 'max_seq': seq,
                                                                  'schema': schemas[owner], key: parts[owner]})
                took[owner] = time.monotonic() - mark

            def apps():  # the backend before the engine, which asks it for the match's targets once restored
                call('backend', 'tables')
                call('engine', 'containers')

            # Nothing reads the restored ETL rows until the runs are released, so the ETL loads alongside.
            with ThreadPoolExecutor(max_workers=2) as owners:
                for future in [owners.submit(call, 'etl', 'tables'), owners.submit(apps)]:
                    future.result()
            log(f"Restored {run['match_id']} from {seed_id} in {time.monotonic() - began:.1f}s "
                f"({', '.join(f'{k} {v:.1f}s' for k, v in took.items())})")

        with ThreadPoolExecutor(max_workers=len(runs) or 1) as pool:
            for future in [pool.submit(restore_one, run) for run in runs]:
                future.result()
        return [http.post(FEED + f"/runs/{run['match_id']}/release",
                          json={'after_seconds': RELEASE_LEAD + i * stagger}).raise_for_status().json()
                for i, run in enumerate(runs)]
    except Exception:
        for run in runs:  # every run, whatever one purge does; the restore's error is what the caller sees
            try:
                purge(http, {'match_id': run['match_id']}, log=lambda _: None)
            except Exception as exc:
                log(f"Could not purge {run['match_id']} after a failed restore: {type(exc).__name__}")
        raise


def record(http, point, from_point=None, log=print):
    """Record a seed at `point`: one held run per demo fixture from kick-off, or from `from_point`'s seed."""
    settings = http.get(FEED + '/demo').raise_for_status().json()
    seed = next((p['seed'] for p in settings['start_points'] if p['id'] == from_point), None) if from_point else None
    if from_point and not seed:
        raise SystemExit(f'{from_point} has no seed yet')
    runs = []
    for fixture in settings['fixtures']:
        body = {'fixture': fixture, 'hold_point': point}
        if seed:
            body['resume_point'] = from_point
        runs.append(http.post(FEED + '/runs', json=body).raise_for_status().json())
    if seed:
        restore_runs(http, seed, runs, 0, log)
    log(f"Recording {point}: {', '.join(r['match_id'] for r in runs)}")


def purge(http, target, owners=OWNERS, log=print):
    for name, url, token in owners:
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        for _ in range(PURGE_RETRIES):
            response = http.post(url, json=target, headers=headers)
            if response.status_code != 503:
                break
            time.sleep(PURGE_RETRY_SECONDS)
        response.raise_for_status()
        body = response.json()
        log(f"Purged {name}: {len(body['match_ids'])} matches {body['purged']}")


def start(http, fixtures):
    known = {r['fixture'] for r in http.get(FEED + '/recordings').raise_for_status().json()}
    missing = [f for f in fixtures if f not in known]
    if missing:
        raise SystemExit(f"Unknown fixture(s) {', '.join(missing)}; the feed lists {', '.join(sorted(known))}")
    purge(http, {'all': True})
    for fixture in fixtures:
        run = http.post(FEED + '/runs', json={'fixture': fixture, 'kickoff': 'next-minute'}).raise_for_status().json()
        print(f"Started {run['match_id']} (kickoff {run['kickoff']})", flush=True)


def app(http=None):
    """The public demo API. Every action is idempotent, and the feed caps concurrent runs, so repeated
    clicks from several viewers start one demo."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, ConfigDict, Field

    class Start(BaseModel):
        model_config = ConfigDict(extra='forbid')
        point: str = Field(default='kickoff', max_length=20)

    api, http = FastAPI(title='Demo control'), http or httpx.Client(timeout=PURGE_TIMEOUT)
    serial = threading.Lock()  # Start and cancel never interleave (one demo-control replica).

    def feed(method, path, **kwargs):
        response = http.request(method, FEED + path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get('detail', 'The feed refused.')
            except ValueError:
                detail = 'The feed is unavailable.'
            raise HTTPException(response.status_code, detail)
        return response.json()

    def split():
        """(the demo's unfinished runs, finished runs, seed-recording runs). A recording (held) run is no demo."""
        runs = feed('GET', '/runs')
        recording = [r for r in runs if r['status'] != 'finished' and r.get('hold_seconds') is not None]
        return ([r for r in runs if r['status'] != 'finished' and r not in recording],
                [r for r in runs if r['status'] == 'finished'], recording)

    @api.get('/health')
    def health():
        return {'status': 'ok'}

    @api.get('/state')
    def state():
        settings, (active, _, _) = feed('GET', '/demo'), split()
        points = [{'id': p['id'], 'label': p['label'],
                   'ready': p['minute'] == 0 and p['period'] == 1 or seed_ready(p['seed'], settings['fixtures'])}
                  for p in settings['start_points']]
        # A demo started from a seed: its runs' clocks began past kick-off ("live from" that point).
        seeded = {p['id']: p for p in settings['start_points'] if p['seed']}
        live_from = next((p['label'] for p in seeded.values() for r in active if r.get('started_from') == p['id']), None)
        # The main game opens by default; the others stay in the picker.
        main = settings.get('main_fixture') or next(iter(settings.get('fixtures') or []), None)
        main_run = next((r for r in active if r['fixture'] == main), None)
        return {'points': points, 'live': bool(active), 'runs': active, 'live_from': live_from,
                'main_fixture': main, 'main_match_id': main_run and main_run['match_id']}

    @api.post('/start')
    def start_demo(body: Start | None = None):
        point, began = (body or Start()).point, time.monotonic()
        for name, (url, token) in checks.items():  # wake every owner now, in parallel, before the purge needs them
            pool.submit(ok, url, token, WAKE_TIMEOUT)
        with serial:
            active, finished, recording = split()
            if active:
                return {'started': False, 'runs': active}
            if recording:  # the recording's held runs hold the feed; a demo would mix with them
                raise HTTPException(409, 'A start point is being recorded; start the demo once it is saved.')
            settings = feed('GET', '/demo')
            chosen = next((p for p in settings['start_points'] if p['id'] == point), None)
            if chosen and chosen.get('seed'):  # refuse a seed that cannot fit before any run exists
                try:
                    seed_manifest(chosen['seed'], settings['fixtures'])
                except SeedStale as exc:
                    raise HTTPException(409, f"The {chosen['label']} start needs recording again ({exc}).") from exc
            for run in finished:  # The feed purges its own finished runs when it starts the demo.
                purge(http, {'match_id': run['match_id']}, OWNERS[1:], log=lambda _: None)
            result = feed('POST', '/demo/start', json={'point': point})
            print(f'Start {point}: runs created in {time.monotonic() - began:.1f}s', flush=True)
            seed = result['started'] and result['point'].get('seed')
            if seed:  # The runs wait for every owner to restore the seed, then start at the point.
                main = result.get('main_fixture') or settings.get('main_fixture')
                try:
                    result['runs'] = restore_runs(http, seed, main_first(result['runs'], main),
                                                  settings['stagger_seconds'], log=lambda line: print(line, flush=True))
                except Exception as exc:  # restore_runs purged the runs: none waits on a seed that will not come
                    if isinstance(exc, SeedStale):
                        raise HTTPException(409, f"The {result['point']['label']} start needs recording again "
                                                 f'({exc}).') from exc
                    raise HTTPException(503, f'Could not restore the {point} seed; try again.') from exc
                result['live_from'] = result['point']['label']
            print(f'Start {point}: ready in {time.monotonic() - began:.1f}s', flush=True)
            return result

    def ok(url, token=None, timeout=CHECK_TIMEOUT):
        try:
            headers = {'Authorization': f'Bearer {token}'} if token else {}
            return http.get(url, headers=headers, timeout=timeout).status_code == 200
        except httpx.HTTPError:
            return False

    backend_url = OWNERS[3][1].removesuffix('/admin/matches/purge')
    checks = {'feed': (FEED + '/health', None),
              'etl': (OWNERS[1][1].removesuffix('/admin/matches/purge') + '/health', OWNERS[1][2]),
              'engine': (OWNERS[2][1].removesuffix('/admin/matches/purge') + '/health', None),
              'backend': (backend_url + '/health', None)}
    pool = ThreadPoolExecutor(max_workers=len(checks))

    def health_all():
        """Every owner's health at once, so apps scaled to zero wake in parallel rather than one by one."""
        futures = {name: pool.submit(ok, url, token) for name, (url, token) in checks.items()}
        return {name: future.result() for name, future in futures.items()}

    @api.get('/status')
    def status():
        """Each pipeline stage from a real check, in flow order. Calling it also wakes apps scaled to zero."""
        ready = health_all()
        feed_ok, etl, engine, backend = ready['feed'], ready['etl'], ready['engine'], ready['backend']
        active = split()[0] if feed_ok else []
        # Staggered runs send MA1 minutes apart; the pipeline is ready once every MA1 sent so far is viewable.
        ids = {r['match_id'] for r in active if r.get('position', 0) >= 1}
        listed = set()
        if backend and ids:
            try:
                listed = {m['match_id'] for m in http.get(backend_url + '/product/matches', timeout=CHECK_TIMEOUT).json()}
            except (httpx.HTTPError, ValueError):
                pass
        # With no demo on, the per-match stages have nothing to wait for: the pipeline is ready once its apps are.
        stages = [('feed', feed_ok), ('event-hubs', bool(ids) or not active),
                  ('etl', etl), ('service-bus', etl and engine), ('engine', engine), ('backend', backend),
                  ('viewer', (bool(ids) and ids <= listed) or not active)]
        return {'live': bool(active), 'matches': len(active),
                'stages': [{'id': name, 'ready': ready} for name, ready in stages]}

    @api.post('/cancel')
    def cancel():
        """Everything the feed lists (finished staggered runs too) goes from every owner, feed first."""
        with serial:
            runs = feed('GET', '/runs')
            if runs:
                purge(http, {'all': True}, log=lambda _: None)
            return {'cancelled': [r['match_id'] for r in runs]}

    return api


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('purge', help='Purge every match from every owner')
    recorder = sub.add_parser('record', help='Seed recording: start one held run per demo fixture')
    recorder.add_argument('point')
    recorder.add_argument('--from', dest='from_point', help='start from this point\'s seed instead of kick-off')
    capturer = sub.add_parser('capture', help='Seed recording: wait for the held runs to settle, then save the seed')
    capturer.add_argument('point')
    starter = sub.add_parser('start', help='Purge, then start one run per fixture at the next whole minute')
    starter.add_argument('fixtures', nargs='*', default=['chelsea-united'])
    server = sub.add_parser('serve', help='Serve the public demo API')
    server.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.action == 'serve':
        import uvicorn
        uvicorn.run(app(), host='0.0.0.0', port=args.port)
    else:
        with httpx.Client(timeout=PURGE_TIMEOUT) as client:
            if args.action == 'purge':
                purge(client, {'all': True})
            elif args.action == 'record':
                record(client, args.point, args.from_point)
            elif args.action == 'capture':
                capture(client, args.point)
            else:
                start(client, args.fixtures)
