"""One shared live match projection; viewer composition never queries upstreams.

This development owner is process-local. A production owner publishes committed,
versioned projections to a fanout service rather than running one replay per API.
"""
import asyncio
import logging
from contextlib import suppress
from uuid import uuid4

from backend.domain import RuleError
from backend.models.stat_offers import pin_id
from .live_viewers import LiveViewers
from .product_audiences import ProductAudiences


class ProductService:
    slots = 5

    def __init__(self, questions, lab, audiences):
        self.questions, self.lab = questions, lab
        self.brokers = None
        self.live = LiveViewers()
        self.audiences = audiences
        self.presence = ProductAudiences(audiences.repository, self.live)
        questions.session_started = self._replace_profile
        self.shared = None
        self.version = 0
        self.projection_epoch = str(uuid4())
        self._refresh_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._task = None
        self._audience_generation = 0
        self._published_audience_generation = 0

    def narratives_changed(self):
        self._audience_generation += 1

    async def initialize(self):
        # A failed replay must not block startup; the viewer is told to start a new run.
        identity = await self.questions.snapshots.identity(allow_error=True)
        await self.presence.initialize(identity.match_id, identity.run_id)
        self._task = asyncio.create_task(self._updates())

    async def close(self):
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        for peer in self.live.active():
            peer.close(1001)
        await self.presence.sync()

    async def _replace_profile(self, profile_id):
        self.live.replace_profile(profile_id)
        await self._sync_presence()

    async def detach(self, peer):
        self.live.detach(peer)
        await self._sync_presence()

    async def _sync_presence(self):
        if getattr(self.questions.narratives, 'audience_dependent', False):
            self._audience_generation += 1
            self.lab.changed.set()
        try:
            await self.presence.sync()
        except Exception:
            # A committed viewer choice must not look rejected to the client.
            # The shared update loop retries and closes stale live transports if
            # persistence remains unavailable; it never invokes generation.
            logging.getLogger(__name__).warning('Audience presence publication delayed', exc_info=True)
            self.lab.changed.set()

    async def _updates(self):
        while True:
            await self.lab.changed.wait()
            self.lab.changed.clear()
            try:
                await self.refresh()
            except RuleError as exc:
                if exc.code != 'snapshot_unavailable':
                    raise
                # Upstream is still consuming the newest deliveries: keep the last consistent
                # state on screen (if any) and try the newer cursor again shortly.
                await asyncio.sleep(0.5)
                self.lab.changed.set()
            except Exception:
                logging.getLogger(__name__).warning('Product projection unavailable', exc_info=True)
                async with self._refresh_lock:
                    self.shared = None
                    # Do not display old data as live. Reconnect retries a fresh read.
                    for peer in self.live.active():
                        peer.close(1013)
                with suppress(Exception):
                    await self.presence.sync()
                await asyncio.sleep(1)
                self.lab.changed.set()

    async def refresh(self):
        async with self._refresh_lock:
            audience_generation = self._audience_generation
            live = await self.questions.snapshots.capture()
            if self.brokers:
                await self.brokers.prepare(live)
            state = await self.lab.state()
            if str(state['run_id']) != live.snapshot.run_id:
                self.lab.changed.set()
                return
            if state['position'] != live.snapshot.cursor:
                # Deliveries outpaced this capture. Publish the consistent captured snapshot rather
                # than starve viewers, and refresh again for the newer one.
                self.lab.changed.set()
            # The next narrative delivery triggers another refresh when this is pinned behind live.
            payload = await self.questions.pin(live)
            state = {**state, 'position': payload.snapshot.cursor}
            # Commit active targets before the narrative service reads them.
            await self.presence.match(payload.snapshot.match_id, payload.snapshot.run_id)
            if self.shared and self.shared['snapshot_id'] == payload.snapshot.id and audience_generation == self._published_audience_generation:
                stats = {'stats': self.shared['stats']}
                narratives = {'events': self.shared['events'], 'items': self.shared['narratives']}
            else:
                await self.questions.match_data.capture(payload, purpose='viewer')
                await self.questions.narratives.capture(payload, purpose='viewer')
                stats, narratives = await asyncio.gather(
                    self.questions.match_data.stats(payload.snapshot),
                    self.questions.narratives.read(payload.snapshot, 'viewer'))
                team_names = {team['id']: team['name'] for team in payload.teams}
                player_names = {player['id']: player['name'] for player in payload.players}
                narratives['events'] = [
                    {**event, 'team_name': team_names.get(event.get('team_id')),
                     'player_name': player_names.get(event.get('player_id'))}
                    for event in narratives['events']]
                self._published_audience_generation = audience_generation
            if (await self.questions.snapshots.identity()).run_id != payload.snapshot.run_id:
                self.lab.changed.set()
                return
            async with self.questions.snapshots.run_guard(payload.snapshot.run_id):
                await self.presence.match(payload.snapshot.match_id, payload.snapshot.run_id)
                self.version += 1
                teams = [{**team, 'score': next((s['value'] for s in stats['stats'] if s['id'] == team['id'] + ':goals'), None)}
                         for team in payload.teams]
                self.shared = {'type': 'snapshot', 'version': self.version, 'synthetic': True,
                    'snapshot_id': payload.snapshot.id, 'projection_epoch': self.projection_epoch,
                    'mode': self.questions.agent.mode,
                    'match': {'id': payload.snapshot.match_id, 'run_id': payload.snapshot.run_id,
                        'status': state['status'], 'clock_seconds': payload.snapshot.clock_seconds,
                        'period': payload.snapshot.period, 'position': state['position'], 'total': state['total'], 'teams': teams},
                    'events': narratives['events'][-30:], 'narratives': narratives['items'][-480:],
                    'stats': stats['stats'], 'calculations': {c['id']: c for c in state['calculations']}}
                if self.lab.source.timed:
                    self.shared['match']['media'] = {'aligned': True, 'seconds': state['playback_seconds'],
                        'sampled_at': state['playback_sampled_at'],
                        'url': '/media/hls/live.m3u8' if self.lab.hls else '/media/simulator.mp4',
                        'live': bool(self.lab.hls)}
                for peer in self.live.active():
                    if peer.viewer['run_id'] != payload.snapshot.run_id:
                        peer.close(4001)
                    else:
                        peer.offer(self.compose(peer.viewer))

    async def _viewer(self, token):
        row = await self.questions.read(token)
        profiles = await self.questions.profiles()
        default = next(p for p in profiles['profiles'] if p['id'] == row['profile_id'])
        audience = row.get('audience') or {key: default[key] for key in ('team', 'fan_style')}
        profile = self._profile({**default, **audience})
        return {**row, 'audience': audience, 'profile': profile}

    def _profile(self, profile):
        teams = self.lab.scenario()['teams']
        index = {'home': 0, 'away': 1}.get(profile['team'])
        team = teams[index] if index is not None and index < len(teams) else None
        return {**profile, 'team': team['id'] if team else 'neutral',
                'display_name': f"{team['name']} · {profile['fan_style']}" if team else profile['display_name']}

    async def reset_demo(self):
        from backend.adapters.product_demo import load_product_demo
        content = await asyncio.to_thread(load_product_demo)
        result = await self.lab.load_recording(content, 'product-demo.json', upstream=True)
        await self.refresh()
        return result

    async def profiles(self):
        result = await self.questions.profiles()
        return {**result, 'profiles': [self._profile(p) for p in result['profiles']]}

    async def start(self, profile_id):
        async with self._session_lock:
            row = await self.questions.start(profile_id)
            return await self.bootstrap(row['session_token'])

    async def bootstrap(self, token):
        viewer = await self._viewer(token)
        identity = await self.questions.snapshots.identity()
        if self.shared is None or self.shared['match']['run_id'] != identity.run_id:
            try:
                await self.refresh()
            except RuleError:
                raise
            except Exception as exc:
                raise RuleError('snapshot_unavailable', 'Live match data is temporarily unavailable.', 503) from exc
        if self.shared is None or self.shared['match']['run_id'] != viewer['run_id']:
            raise RuleError('snapshot_unavailable', 'The match is updating. Please reconnect.', 503)
        return {**viewer, 'snapshot': self.compose(viewer)}

    def compose(self, viewer):
        shared, profile = self.shared, viewer['profile']
        teams = shared['match']['teams']
        support = profile['team'] if profile['team'] in {t['id'] for t in teams} else 'neutral'
        bucket = f"{support}:{profile['fan_style']}"
        bucket_id = f"{viewer['audience']['team']}:{viewer['audience']['fan_style']}"
        routing_ids = {bucket_id, bucket}  # Prewritten fixtures still use team IDs.
        pins = {o['calculation_id']: o for o in viewer['offers'] if o.get('calculation_id')}
        available = {s['id']: s for s in shared['stats']}
        tracked = []
        for identifier, offer in list(pins.items())[-self.slots:]:
            if offer.get('kind') == 'standard':
                stat_id = offer['standard_stat_id']
                stat = available.get(stat_id, {'id': stat_id, 'label': offer['label'],
                                               'value': None, 'available': False, 'complete': False})
                tracked.append({**stat, 'kind': 'standard', 'pinned': True, 'pin_id': identifier})
            elif identifier in shared['calculations']:
                tracked.append({**shared['calculations'][identifier], 'kind': 'custom',
                                'pinned': True, 'pin_id': identifier})
        # Narrative recommendations reference ETL's approved catalogue.
        stat_ids = next((n['stat_ids'] for n in reversed(shared['narratives']) if routing_ids.intersection(n['buckets'])),
                        [f"{support if support != 'neutral' else 'all'}:{kind}" for kind in ('goals','shots','corners','passes','cards')])
        pinned_standard = {card['id'] for card in tracked if card['kind'] == 'standard'}
        fallback = [f"{support if support != 'neutral' else 'all'}:{kind}"
                    for kind in ('goals', 'shots', 'passes', 'possession', 'pass_accuracy')]
        if any(i in available and not available[i].get('available', True) for i in stat_ids):
            stat_ids = [*stat_ids, *fallback]
        # Both teams' possession is 100% by definition: a split question, never a card.
        defaults = [{**available[i], 'kind': 'standard'} for i in dict.fromkeys(stat_ids)
                    if i in available and available[i].get('available', True) and i not in pinned_standard
                    and i != 'all:possession']
        return {key: shared[key] for key in ('type','version','projection_epoch','synthetic','mode','match','events')} | {
            'profile': profile, 'audience': viewer['audience'], 'bucket': bucket, 'bucket_id': bucket_id,
            'cards': defaults[:self.slots - len(tracked)] + tracked,
            'narratives': [n for n in shared['narratives'] if routing_ids.intersection(n['buckets'])]}

    @staticmethod
    def _subscription(viewer):
        # Live delivery retains routing/pin IDs, never the viewer's chat transcript.
        return {key: viewer[key] for key in ('run_id', 'profile_id', 'profile', 'audience')} | {
            'offers': [{key: offer[key] for key in ('calculation_id', 'kind', 'standard_stat_id', 'label')
                        if key in offer} for offer in viewer['offers'] if offer.get('calculation_id')]}

    async def attach(self, token):
        async with self._session_lock, self.questions.session_guard():
            data = await self.bootstrap(token)
            peer = self.live.attach(str(token), self._subscription(data))
            try:
                await self.presence.sync()
                if getattr(self.questions.narratives, 'audience_dependent', False):
                    self._audience_generation += 1
                    self.lab.changed.set()
            except Exception as exc:
                self.live.detach(peer)
                raise RuleError('audience_unavailable', 'Audience settings are temporarily unavailable.', 503) from exc
            return peer, data['snapshot']

    async def select_audience(self, token, audience):
        async with self._session_lock, self.questions.session_guard():
            viewer = await self.bootstrap(token)
            catalog, _ = await self.audiences.read(viewer['match_id'])
            if not any(bucket['selections'] == audience.model_dump() for bucket in catalog['buckets']):
                raise RuleError('audience_unavailable', 'This audience is not configured for the match.', 422)
            async with self._refresh_lock, self.questions.snapshots.run_guard(viewer['run_id']):
                if self.shared is None:
                    raise RuleError('snapshot_unavailable', 'Live match data is temporarily unavailable.', 503)
                await asyncio.to_thread(self.questions.repository.set_audience, token, audience)
                viewer['audience'] = audience.model_dump()
                viewer['profile'] = self._profile({**viewer['profile'], **viewer['audience']})
                self.live.update(str(token), self._subscription(viewer))
                await self._sync_presence()
                self.version += 1
                self.shared['version'] = self.version
                snapshot = self.compose(viewer)
                if peer := self.live.peers.get(str(token)):
                    peer.offer(snapshot)
                return {**viewer, 'snapshot': snapshot}

    async def track(self, token, offer_id):
        async with self._session_lock:
            viewer = await self._viewer(token)
            offer = next((o for o in viewer['offers'] if o['id'] == str(offer_id)), None)
            if offer is None:
                raise RuleError('offer_not_found', 'This offer is not in your conversation.', 404)
            identifier = pin_id(offer)
            pins = {o['calculation_id'] for o in viewer['offers'] if o.get('calculation_id')}
            if identifier not in pins and len(pins) >= self.slots:
                raise RuleError('cards_full', 'Remove a tracked stat before adding another.', 409)
            result = await self.questions.track(token, offer_id)
            viewer = await self._viewer(token)
            self.live.update(str(token), self._subscription(viewer))
            await self.refresh()
            return {**result, 'snapshot': self.compose(viewer)}

    async def untrack(self, token, calculation_id):
        async with self._session_lock:
            await self.questions.read(token)
            await asyncio.to_thread(self.questions.repository.untrack, token, calculation_id)
            viewer = await self._viewer(token)
            self.live.update(str(token), self._subscription(viewer))
            # Publication is yield-free, like refresh: older queued snapshots
            # cannot restore a removed pin after the HTTP result is applied.
            if self.shared is None:
                raise RuleError('snapshot_unavailable', 'Live match data is temporarily unavailable.', 503)
            self.version += 1
            self.shared['version'] = self.version
            snapshot = self.compose(viewer)
            if peer := self.live.peers.get(str(token)):
                peer.offer(snapshot)
            return {'snapshot': snapshot}
