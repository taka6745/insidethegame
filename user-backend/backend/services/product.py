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


class ProductService:
    slots = 5

    def __init__(self, questions, lab):
        self.questions, self.lab = questions, lab
        self.live = LiveViewers()
        questions.session_started = self.live.replace_profile
        self.shared = None
        self.version = 0
        self.projection_epoch = str(uuid4())
        self._refresh_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._task = None

    async def initialize(self):
        self._task = asyncio.create_task(self._updates())

    async def close(self):
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        for peer in self.live.active():
            peer.close(1001)

    async def _updates(self):
        while True:
            await self.lab.changed.wait()
            self.lab.changed.clear()
            try:
                await self.refresh()
            except Exception:
                logging.getLogger(__name__).warning('Product projection unavailable', exc_info=True)
                self.shared = None
                # Do not display old data as live. Reconnect retries a fresh read.
                for peer in self.live.active():
                    peer.close(1013)
                await asyncio.sleep(1)
                self.lab.changed.set()

    async def refresh(self):
        async with self._refresh_lock:
            payload = await self.questions.snapshots.capture()
            state = await self.lab.state()
            if state['position'] != payload.snapshot.cursor or str(state['run_id']) != payload.snapshot.run_id:
                self.lab.changed.set()
                return
            if self.shared and self.shared['snapshot_id'] == payload.snapshot.id:
                stats = {'stats': self.shared['stats']}
                narratives = {'events': self.shared['events'], 'items': self.shared['narratives']}
            else:
                await asyncio.gather(self.questions.match_data.capture(payload, purpose='viewer'),
                                     self.questions.narratives.capture(payload, purpose='viewer'))
                stats, narratives = await asyncio.gather(
                    self.questions.match_data.stats(payload.snapshot),
                    self.questions.narratives.read(payload.snapshot, 'viewer'))
                team_names = {team['id']: team['name'] for team in payload.teams}
                player_names = {player['id']: player['name'] for player in payload.players}
                narratives['events'] = [
                    {**event, 'team_name': team_names.get(event.get('team_id')),
                     'player_name': player_names.get(event.get('player_id'))}
                    for event in narratives['events']]
            if (await self.questions.snapshots.identity()).run_id != payload.snapshot.run_id:
                self.lab.changed.set()
                return
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
            for peer in self.live.active():
                if peer.viewer['run_id'] != payload.snapshot.run_id:
                    peer.close(4001)
                else:
                    peer.offer(self.compose(peer.viewer))

    async def _viewer(self, token):
        row = await self.questions.read(token)
        profiles = await self.questions.profiles()
        profile = self._profile(next(p for p in profiles['profiles'] if p['id'] == row['profile_id']))
        return {**row, 'profile': profile}

    def _profile(self, profile):
        teams = self.lab.scenario()['teams']
        index = {'home': 0, 'away': 1}.get(profile['team'])
        team = teams[index] if index is not None and index < len(teams) else None
        return {**profile, 'team': team['id'] if team else 'neutral',
                'display_name': f"{team['name']} · {profile['fan_style']}" if team else profile['display_name']}

    async def reset_demo(self):
        from backend.adapters.product_demo import load_product_demo
        content = await asyncio.to_thread(load_product_demo)
        result = await self.lab.load_recording(content, 'product-demo.json')
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
        # The fake narrative service owns the ordered approved-stat recommendation.
        stat_ids = next((n['stat_ids'] for n in reversed(shared['narratives']) if bucket in n['buckets']),
                        [f"{support if support != 'neutral' else 'all'}:{kind}" for kind in ('goals','shots','corners','passes','cards')])
        pinned_standard = {card['id'] for card in tracked if card['kind'] == 'standard'}
        defaults = [{**available[i], 'kind': 'standard'} for i in dict.fromkeys(stat_ids)
                    if i in available and i not in pinned_standard]
        return {key: shared[key] for key in ('type','version','projection_epoch','synthetic','mode','match','events')} | {
            'profile': profile, 'bucket': bucket,
            'cards': defaults[:self.slots - len(tracked)] + tracked,
            'narratives': [n for n in shared['narratives'] if bucket in n['buckets']]}

    @staticmethod
    def _subscription(viewer):
        # Live delivery retains routing/pin IDs, never the viewer's chat transcript.
        return {key: viewer[key] for key in ('run_id', 'profile_id', 'profile')} | {
            'offers': [{key: offer[key] for key in ('calculation_id', 'kind', 'standard_stat_id', 'label')
                        if key in offer} for offer in viewer['offers'] if offer.get('calculation_id')]}

    async def attach(self, token):
        async with self._session_lock, self.questions.session_guard():
            data = await self.bootstrap(token)
            peer = self.live.attach(str(token), self._subscription(data))
            return peer, data['snapshot']

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
