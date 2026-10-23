"""Demo control: the operator between the simulated provider and our services. Not a product service.

CLI (local): `purge` every match from every owner; `start [fixture…]` purges, then starts feed runs from 00:00.
HTTP (`serve`, behind the frontend's public /demo-api/): start the configured demo, cancel it, read its state.
Purge order (local/contracts/README.md): feed, ETL, engine, backend. Configuration stays."""
import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx


@dataclass(frozen=True)
class Owner:
    """A service that keeps per-match rows: its base URL and optional admin token."""
    name: str
    url: str
    token: str | None = None

    @property
    def headers(self):
        return {'Authorization': f'Bearer {self.token}'} if self.token else {}


FEED = os.environ.get('DEMO_FEED_URL', 'http://feed:8000')
OWNERS = (Owner('feed', FEED),
          Owner('etl', os.environ.get('ETL_ADMIN_URL', 'http://etl-stream:8000'), os.environ.get('ETL_ADMIN_TOKEN')),
          Owner('engine', os.environ.get('ENGINE_ADMIN_URL', 'http://narrative-live:8000'),
                os.environ.get('ENGINE_ADMIN_TOKEN')),
          Owner('backend', os.environ.get('BACKEND_URL', 'http://backend:8000')))
OWNER = {owner.name: owner for owner in OWNERS}
CONSUMERS = OWNERS[1:]  # every owner but the feed: the Event Hubs consumers


def _number(name, default):
    """An env override of the default's type (seconds are floats, so `0.5` works)."""
    return type(default)(os.environ.get(name, default))


PURGE_TIMEOUT = _number('DEMO_PURGE_TIMEOUT', 300.0)  # Seconds; a purge waits for the stream's current batch.
PURGE_RETRIES = _number('DEMO_PURGE_RETRIES', 10)  # 503 means retry; purge is idempotent.
PURGE_RETRY_SECONDS = _number('DEMO_PURGE_RETRY_SECONDS', 2.0)
CHECK_TIMEOUT = 3  # Seconds per readiness probe.
# /status fans out to every owner; callers within this many seconds (or while a check runs) share one answer, so
# its public per-client limit (nginx) never multiplies into probe load on the owners.
STATUS_CACHE_SECONDS = _number('DEMO_STATUS_CACHE_SECONDS', 1.0)
WAKE_TIMEOUT = 60  # Seconds a wake-up call waits for an app scaled to zero.
# While a demo is live, every app it needs is pinged this often so none scales to zero mid-match (Container Apps
# scale down after a 300 s quiet cooldown); with no demo the pings stop and the apps idle back to zero.
KEEP_WARM_SECONDS = _number('DEMO_KEEP_WARM_SECONDS', 60.0)
# The sweep purges a finished run only once no demo is live and the run has been finished this long, so the engine's
# late full-time steps land and viewers keep the match at full time; a start purges any leftovers itself.
SWEEP_GRACE_SECONDS = _number('DEMO_SWEEP_GRACE_SECONDS', 900.0)
# Extra URLs to keep warm beyond the owners' health checks (comma-separated), e.g. the ETL data API and this app.
KEEP_WARM_URLS = [u for u in os.environ.get('DEMO_KEEP_WARM_URLS', '').split(',') if u.strip()]
# Azure only: the spend guard's stream-start webhook (a secret URL). Stream Analytics otherwise starts on an Event Hubs
# traffic alert, minutes after a demo's first events; a Start asks for it at once (a no-op while it runs).
STREAM_START_URL = os.environ.get('DEMO_STREAM_START_URL', '')
SEED_ROOT = Path(os.environ.get('DEMO_SEED_ROOT', '/seeds'))  # seeds/{seed_id}/: manifest + one file per owner
SEED_OWNERS = ('etl', 'engine', 'backend')  # restore_runs: the ETL alongside the backend, then the engine
RELEASE_LEAD = _number('DEMO_RELEASE_LEAD', 5.0)  # Seconds from the last restore to the first run reading the point.
CAPTURE_POLL = _number('DEMO_CAPTURE_POLL', 5.0)  # Seconds: a held run's owners must settle before a capture.
CAPTURE_TIMEOUT = _number('DEMO_CAPTURE_TIMEOUT', 1800.0)
SEED_FORMAT = 2  # manifest layout; 2 adds each owner's schema fingerprint and the source run id


class SeedStale(RuntimeError):
    """A seed this pipeline cannot restore (another format or owner schema, or another start point)."""


def owner_call(http, name, path, body):
    url, headers = OWNER[name].url + path, OWNER[name].headers
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
        other = sorted({str(r.get('held_at')) for r in runs if r.get('held_at') != point})
        if other:  # a seed named for one point but holding another would read ready, then fail every Start
            raise SystemExit(f"The held runs stop at {', '.join(other)}, not {point}; record {point} first")
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
    name_seed(http, point, seed_id)
    for run in runs:  # the recording is done: its runs leave every owner
        purge(http, {'match_id': run['match_id']}, log=lambda _: None)
    log(f'Seed {seed_id}: {fixtures}')
    return seed_id


def name_seed(http, point, seed_id):
    """Offer `seed_id` at the feed's start point `point`."""
    settings = http.get(FEED + '/demo').raise_for_status().json()
    points = [{**p, 'seed': seed_id} if p['id'] == point else p for p in settings['start_points']]
    body = {k: v for k, v in settings.items() if k not in ('start_points', 'revision')}
    http.put(FEED + '/demo', json={**body, 'start_points': points, 'expected_revision': settings['revision']}
             ).raise_for_status()


def adopt(http, seed_id, log=print):
    """Offer a seed recorded on another stack (copied into SEED_ROOT) at its own start point. Each owner still
    checks its schema fingerprint and the feed its seq at Start."""
    settings = http.get(FEED + '/demo').raise_for_status().json()
    try:
        manifest = seed_manifest(seed_id, settings['fixtures'])
    except SeedStale as exc:
        raise SystemExit(str(exc)) from exc
    if manifest.get('seed_id') != seed_id or manifest['point'] not in {p['id'] for p in settings['start_points']}:
        raise SystemExit(f"seed {seed_id} is for point {manifest.get('point')}, which this feed does not offer")
    name_seed(http, manifest['point'], seed_id)
    log(f"Seed {seed_id} offered at {manifest['point']}")


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


# Seed files never change under a seed id, and reading one from the share is seconds at 60′: the start points'
# seeds are read once into memory (preload_seeds, when the picker asks /state) and kept while they are offered.
_seed_texts, _seed_lock = {}, threading.Lock()


def seed_text(seed_id, owner, fixture):
    path = SEED_ROOT / seed_id / owner / f'{fixture}.json'
    text = _seed_texts.get(path)
    if text is None:
        text = path.read_text()
        with _seed_lock:
            _seed_texts[path] = text
    return text


def preload_seeds(seed_ids, fixtures):
    """Read these seeds' files into memory and forget any other seed's (re-recorded or no longer offered)."""
    with _seed_lock:
        for path in [p for p in _seed_texts if p.parents[1] not in {SEED_ROOT / s for s in seed_ids}]:
            del _seed_texts[path]
    for seed_id in seed_ids:
        for owner in SEED_OWNERS:
            for fixture in fixtures:
                try:
                    seed_text(seed_id, owner, fixture)
                except OSError:
                    pass  # a missing file is refused at start (seed_manifest / restore), not here


def seed_parts(seed_id, manifest, fixture, match_id, run_id):
    """One fixture's seed, rewritten for a new run: its matchId and runId everywhere, and its MA1 as sent now."""
    source = manifest['fixtures'][fixture]

    def moved(text):
        return text.replace(source['source_match_id'], match_id).replace(source['source_run_id'], run_id)

    parts = {owner: json.loads(moved(seed_text(seed_id, owner, fixture))) for owner in SEED_OWNERS}
    now = datetime.now(timezone.utc).isoformat()
    for row in parts['etl'].get('matches', []):  # the run's MA1 counts as sent now (purge-all cut-offs)
        payload = json.loads(row['payload'])
        row['payload'] = json.dumps({**payload, 'timeStamp': now.replace('+00:00', 'Z')})
    for row in parts['backend'].get('received_matches', []):
        row.update(run_id=run_id, sent_at=now)
    return parts, source['seq']


def main_first(runs, main):
    return sorted(runs, key=lambda run: run['fixture'] != main)  # stable: the rest keep their order


def restore_runs(http, seed_id, runs, stagger, log=print, before_release=lambda: None):
    """Restore every owner for each run waiting on the seed, then release the runs, staggered in the order given
    (the main game first: it stays furthest along). `before_release` runs between the two (the previous demo's
    purge, overlapped with the restore). A failure purges the runs everywhere; SeedStale when the seed no longer
    fits (record it again)."""
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
        before_release()
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


def purge_owner(http, owner, target, log=print):
    for _ in range(PURGE_RETRIES):
        response = http.post(owner.url + '/admin/matches/purge', json=target, headers=owner.headers)
        if response.status_code != 503:
            break
        time.sleep(PURGE_RETRY_SECONDS)
    response.raise_for_status()
    body = response.json()
    log(f"Purged {owner.name}: {len(body['match_ids'])} matches {body['purged']}")


def purge(http, target, owners=OWNERS, log=print):
    for owner in owners:  # in order: the feed first, so nothing new reaches the others mid-purge
        purge_owner(http, owner, target, log)


def purge_matches(http, match_ids, owners, log=print):
    """Each match from each owner, all at once (they are independent); every pair is tried, the first error raised."""
    pairs = [(owner, match_id) for match_id in match_ids for owner in owners]
    if not pairs:
        return
    with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
        futures = [pool.submit(purge_owner, http, owner, {'match_id': match_id}, log) for owner, match_id in pairs]
    errors = [f.exception() for f in futures if f.exception()]
    if errors:
        raise errors[0]


def start(http, fixtures):
    known = {r['fixture'] for r in http.get(FEED + '/recordings').raise_for_status().json()}
    missing = [f for f in fixtures if f not in known]
    if missing:
        raise SystemExit(f"Unknown fixture(s) {', '.join(missing)}; the feed lists {', '.join(sorted(known))}")
    purge(http, {'all': True})
    for fixture in fixtures:
        run = http.post(FEED + '/runs', json={'fixture': fixture, 'kickoff': 'next-minute'}).raise_for_status().json()
        print(f"Started {run['match_id']} (kickoff {run['kickoff']})", flush=True)


def app(http=None, clock=time.monotonic):
    """The public demo API. Every action is idempotent, and the feed caps concurrent runs, so repeated
    clicks from several viewers start one demo."""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, ConfigDict, Field

    class Start(BaseModel):
        model_config = ConfigDict(extra='forbid')
        point: str = Field(default='kickoff', max_length=20)

    class Skip(BaseModel):
        model_config = ConfigDict(extra='forbid')
        target: str = Field(max_length=20)

    from fastapi.responses import JSONResponse

    api, http = FastAPI(title='Demo control'), http or httpx.Client(timeout=PURGE_TIMEOUT)
    serial = threading.Lock()  # Start and cancel never interleave (one demo-control replica).
    # Start and cancel answer at once (202) and run here one after another; /state reports what is pending and
    # how the last one ended, so no request waits on a purge or a seed restore (minutes under load).
    jobs, book = ThreadPoolExecutor(max_workers=1), threading.Lock()
    work = {'pending': [], 'last': None}
    # Finished runs already purged from the other owners (the feed keeps listing them until the next start purges
    # its own), so a start does not purge them again. Purging is a few slow calls per run; done here between demos.
    swept, background = set(), ThreadPoolExecutor(max_workers=2)
    # Start's cleanup has its own worker, so cold keep-warm wakes on `background` cannot delay the release it gates.
    cleaner = ThreadPoolExecutor(max_workers=1)
    finished_at = {}  # match_id -> clock() when the sweep first saw it finished (the feed lists no finish time)
    # The seed ids last read into memory (preload_seeds), and when a viewer at the picker last woke the owners.
    preloaded = {'seeds': frozenset(), 'woken': None}

    def submit(action, run):
        def job():
            try:
                work['last'] = {'action': action, 'ok': True, **run()}
            except HTTPException as exc:
                work['last'] = {'action': action, 'ok': False, 'status': exc.status_code, 'detail': exc.detail}
            except Exception as exc:  # noqa: BLE001 - reported on /state; the viewer retries
                print(f'{action} failed: {type(exc).__name__}: {exc}', flush=True)
                work['last'] = {'action': action, 'ok': False, 'status': 503,
                                'detail': f'Could not {action} the demo; try again.'}
            finally:
                with book:
                    work['pending'].remove(action)
        with book:
            work['pending'].append(action)
            jobs.submit(job)
        return JSONResponse({'accepted': True, 'pending': list(work['pending'])}, status_code=202)

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
        settings, (active, _, recording) = feed('GET', '/demo'), split()
        points = [{'id': p['id'], 'label': p['label'],
                   'ready': p['minute'] == 0 and p['period'] == 1 or seed_ready(p['seed'], settings['fixtures'])}
                  for p in settings['start_points']]
        offered = frozenset(p['seed'] for p, q in zip(settings['start_points'], points) if q['ready'] and p['seed'])
        if offered != preloaded['seeds']:  # a viewer is at the picker: have the seeds in memory before Start
            preloaded['seeds'] = offered
            background.submit(preload_seeds, offered, tuple(settings['fixtures']))
        if not active and (preloaded['woken'] is None or clock() - preloaded['woken'] >= KEEP_WARM_SECONDS):
            preloaded['woken'] = clock()  # and wake the owners now: a cold app took ~20 s of a seeded start
            wake()
        # A demo started from a seed: its runs' clocks began past kick-off ("live from" that point).
        seeded = {p['id']: p for p in settings['start_points'] if p['seed']}
        live_from = next((p['label'] for p in seeded.values() for r in active if r.get('started_from') == p['id']), None)
        # The main game opens by default; the others stay in the picker.
        main = settings.get('main_fixture') or next(iter(settings.get('fixtures') or []), None)
        main_run = next((r for r in active if r['fixture'] == main), None)
        return {'points': points, 'live': bool(active), 'runs': active, 'live_from': live_from,
                'main_fixture': main, 'main_match_id': main_run and main_run['match_id'],
                # Seed-recording runs stop at their hold point: viewers must not open them (they would freeze there).
                'recording': [{'match_id': r['match_id']} for r in recording],
                # Skip ahead (demo fast-forward): offered while a demo plays.
                'skips': [{'id': t['id'], 'label': t['label']} for t in settings.get('skip_targets') or []]
                if active else [],
                'pending': list(work['pending']), 'last': work['last']}

    def refuse_start(point):
        """A start that cannot happen, refused at once: a recording holds the feed, or the seed no longer fits."""
        if split()[2]:  # the recording's held runs hold the feed; a demo would mix with them
            raise HTTPException(409, 'A start point is being recorded; start the demo once it is saved.')
        settings = feed('GET', '/demo')
        chosen = next((p for p in settings['start_points'] if p['id'] == point), None)
        if chosen and chosen.get('seed'):  # refuse a seed that cannot fit before any run exists
            try:
                seed_manifest(chosen['seed'], settings['fixtures'])
            except SeedStale as exc:  # the reason goes to the log; viewers get a plain sentence
                print(f"Seed {chosen['id']} refused: {exc}", flush=True)
                raise HTTPException(409, f"The {chosen['label']} start isn't available right now. "
                                         'Pick another start point.') from exc

    @api.post('/start')
    def start_demo(body: Start | None = None):
        point = (body or Start()).point
        if STREAM_START_URL:  # its own thread: wakes and seed preloads on `background` must not delay it
            threading.Thread(target=start_stream, daemon=True).start()
        wake()
        if not work['pending']:
            active = split()[0]
            if active:
                return {'started': False, 'runs': active}
        refuse_start(point)
        return submit('start', lambda: run_start(point))

    def run_start(point):
        began = time.monotonic()
        with serial:
            active, finished, recording = split()
            if active:
                return {'started': False, 'runs': active}
            refuse_start(point)
            settings = feed('GET', '/demo')
            # The previous demo's finished runs: usually swept already (see sweep). The rest go from the other owners
            # alongside the new runs' creation and restore (their matches are independent); the feed purges its own
            # finished runs when it starts the demo. Joined before the new runs are released, so viewers only ever
            # list the new three.
            stale = [r['match_id'] for r in finished if r['match_id'] not in swept]
            cleanup = cleaner.submit(purge_matches, http, stale, CONSUMERS, lambda _: None)

            def cleaned():
                try:
                    cleanup.result()
                    swept.update(stale)
                except Exception as exc:  # noqa: BLE001 - the sweep retries; the new demo is not held up
                    print(f'Purging the previous demo failed: {type(exc).__name__}: {exc}', flush=True)
            result = feed('POST', '/demo/start', json={'point': point})
            print(f'Start {point}: runs created in {time.monotonic() - began:.1f}s', flush=True)
            seed = result['started'] and result['point'].get('seed')
            if not seed:
                cleaned()
            if seed:  # The runs wait for every owner to restore the seed, then start at the point.
                main = result.get('main_fixture') or settings.get('main_fixture')
                try:
                    result['runs'] = restore_runs(http, seed, main_first(result['runs'], main),
                                                  settings['stagger_seconds'], log=lambda line: print(line, flush=True),
                                                  before_release=cleaned)
                except Exception as exc:  # restore_runs purged the runs: none waits on a seed that will not come
                    print(f'Seed restore for {point} failed: {type(exc).__name__}: {exc}', flush=True)
                    if isinstance(exc, SeedStale):
                        raise HTTPException(409, f"The {result['point']['label']} start isn't available right now. "
                                                 'Pick another start point.') from exc
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

    backend_url = OWNER['backend'].url
    checks = {o.name: (o.url + '/health', o.token) for o in OWNERS}
    pool = ThreadPoolExecutor(max_workers=len(checks))

    def wake():
        """Wake every owner in parallel (apps scaled to zero start on a request), and every other app the demo
        needs (the ETL data API, ...); nothing waits on it."""
        for url, token in checks.values():
            pool.submit(ok, url, token, WAKE_TIMEOUT)
        for url in KEEP_WARM_URLS:
            background.submit(ok, url.strip(), None, WAKE_TIMEOUT)

    def start_stream():
        """Ask the spend guard to start Stream Analytics now (its URL is a secret: never logged)."""
        try:
            print(f'Stream start requested: HTTP {http.post(STREAM_START_URL, timeout=WAKE_TIMEOUT).status_code}',
                  flush=True)
        except httpx.HTTPError as exc:
            print(f'Stream start request failed: {type(exc).__name__}', flush=True)

    def health_all():
        """Every owner's health at once, so apps scaled to zero wake in parallel rather than one by one."""
        futures = {name: pool.submit(ok, url, token) for name, (url, token) in checks.items()}
        return {name: future.result() for name, future in futures.items()}

    def keep_warm_once():
        """One round: while a demo is live, touch every app it needs. Returns whether a demo was live."""
        try:
            live = bool(split()[0])
        except (HTTPException, httpx.HTTPError, ValueError):
            return False
        if live:
            health_all()
            for url in KEEP_WARM_URLS:
                ok(url.strip(), timeout=WAKE_TIMEOUT)
        return live

    def sweep_once():
        """Purge finished runs from the other owners between demos, so the next start need not. Only once no demo
        is live (its finished staggered runs stay watchable) and each run has been finished SWEEP_GRACE_SECONDS.
        The targets are chosen under `serial` but purged outside it, so a start, cancel or skip never waits on a
        sweep's purge (a start purges any match the sweep has not finished itself). Returns the matches purged."""
        if work['pending'] or not serial.acquire(blocking=False):
            return []
        try:
            runs = feed('GET', '/runs')
            listed = {r['match_id'] for r in runs}
            swept.intersection_update(listed)  # forget matches the feed no longer lists
            now = clock()
            for match_id in list(finished_at):
                if match_id not in listed:
                    del finished_at[match_id]
            for r in runs:
                if r['status'] == 'finished':
                    finished_at.setdefault(r['match_id'], now)
            if any(r['status'] != 'finished' for r in runs):  # a demo (or a recording) is on: keep its matches
                return []
            stale = [r['match_id'] for r in runs if r['status'] == 'finished' and r['match_id'] not in swept
                     and now - finished_at[r['match_id']] >= SWEEP_GRACE_SECONDS]
        except (HTTPException, httpx.HTTPError, ValueError) as exc:
            print(f'Sweep failed: {type(exc).__name__}', flush=True)
            return []
        finally:
            serial.release()
        if not stale or work['pending']:
            return []
        try:
            purge_matches(http, stale, CONSUMERS, lambda _: None)
        except Exception as exc:  # noqa: BLE001 - the next round or the next start retries
            print(f'Sweep failed: {type(exc).__name__}', flush=True)
            return []
        swept.update(stale)
        return stale

    def keep_warm():
        while True:
            keep_warm_once()
            sweep_once()
            time.sleep(KEEP_WARM_SECONDS)

    api.state.sweep_once = sweep_once  # one round, for tests
    api.state.keep_warm_once = keep_warm_once  # one round, for tests
    api.state.keep_warm = keep_warm  # the loop; `serve` runs it in a thread

    checked, checking = {'at': 0.0, 'body': None}, threading.Lock()

    @api.get('/status')
    def status():
        """Each pipeline stage from a real check, in flow order. Calling it also wakes apps scaled to zero."""
        def current():
            return checked['body'] is not None and time.monotonic() - checked['at'] < STATUS_CACHE_SECONDS
        if checked['body'] is not None and (current() or checking.locked()):
            return checked['body']  # fresh, or a check is already running: share it rather than queue behind it
        with checking:
            if not current():
                checked['body'], checked['at'] = check_status(), time.monotonic()
            return checked['body']

    def check_status():
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

    @api.post('/skip')
    def skip(body: Skip):
        """Move the live demo on (the feed sends what became due at once; video jumps; no new matchIds, so
        follows and sessions carry on). Quick, so it answers directly; never while a start or cancel runs."""
        if work['pending']:
            raise HTTPException(409, 'The demo is starting or stopping; try again in a moment.')
        with serial:
            result = feed('POST', '/demo/skip', json={'target': body.target})
        print(f"Skip {body.target}: {result['skipped_seconds']} s", flush=True)
        return result

    @api.post('/cancel')
    def cancel():
        """Everything the feed lists (finished staggered runs too) goes from every owner, feed first."""
        if not work['pending'] and not feed('GET', '/runs'):
            return {'cancelled': []}
        return submit('cancel', run_cancel)

    def run_cancel():
        with serial:
            runs = feed('GET', '/runs')
            if runs:  # the feed first (nothing new reaches the others), then the others at once
                purge_owner(http, OWNER['feed'], {'all': True}, lambda _: None)
                with ThreadPoolExecutor(max_workers=len(CONSUMERS)) as others:
                    for future in [others.submit(purge_owner, http, o, {'all': True}, lambda _: None)
                                   for o in CONSUMERS]:
                        future.result()
                swept.clear()  # the feed no longer lists them either
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
    adopter = sub.add_parser('adopt', help='Offer a seed copied from another stack at its start point')
    adopter.add_argument('seed_id')
    starter = sub.add_parser('start', help='Purge, then start one run per fixture at the next whole minute')
    starter.add_argument('fixtures', nargs='*', default=['riverton-forgeham'])
    server = sub.add_parser('serve', help='Serve the public demo API')
    server.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.action == 'serve':
        import uvicorn
        served = app()
        if KEEP_WARM_SECONDS > 0:
            threading.Thread(target=served.state.keep_warm, name='keep-warm', daemon=True).start()
        uvicorn.run(served, host='0.0.0.0', port=args.port)
    else:
        with httpx.Client(timeout=PURGE_TIMEOUT) as client:
            if args.action == 'purge':
                purge(client, {'all': True})
            elif args.action == 'record':
                record(client, args.point, args.from_point)
            elif args.action == 'capture':
                capture(client, args.point)
            elif args.action == 'adopt':
                adopt(client, args.seed_id)
            else:
                start(client, args.fixtures)
