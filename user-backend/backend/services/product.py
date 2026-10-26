"""Viewer projections: one shared projection per live match; composing a viewer's cards and
feed never queries upstreams.

Each projection is process-local. A production owner publishes committed, versioned
projections to a fanout service rather than projecting in every API replica."""
import asyncio
import logging
from contextlib import suppress
from uuid import uuid4

from backend.adapters.hls_media import stream_path
from backend.domain import RuleError
from backend.models.engine_narratives import EngineFollowClip, EngineMomentClip
from backend.models.events import DETAIL_FIELDS
from backend.models.questions import MatchSnapshot
from backend.models.stat_offers import pin_id, split_pin_id, viewer_pin_id
from backend.models.viewer_audience import bucket_label, supported_side
from backend.services.live_viewers import LiveViewers
from backend.services.locks import KeyedLocks
from backend.services.cross_match import TEAM_FIELDS
from backend.services.follow_clips import moment_playlists
from backend.services.key_moments import feed_moments
from backend.services.observed import observed

log = logging.getLogger(__name__)
STATUS_ORDER = {'live': 0, 'scheduled': 1, 'finished': 2}
# The feed's last 30 events come from the newest deliveries; a correction is a later delivery, so
# it is in this window too. Folding the whole history per snapshot grew with the match.
RECENT_DELIVERIES = 600


def match_status(match, events):
    """`finished` after the final period's end, `live` once play has events, else `scheduled`."""
    final = ((match.info or {}).get('capabilities') or {}).get('periods', 2)
    if match.closed_through(len(events)) >= final:
        return 'finished'
    return 'live' if events else 'scheduled'


def header_of(match):
    """A published match's header for content from it in another match's viewer: teams without the score."""
    return {'id': match['id'], 'fixture': match['fixture'],
            'teams': [{k: t.get(k) for k in TEAM_FIELDS} for t in match['teams']]}


def sources(viewer, match_id):
    """The other matches a viewer reads from: a cross-match follow and pins from another match."""
    found = {split_pin_id(o['calculation_id'])[1] for o in viewer.get('offers', []) if o.get('calculation_id')}
    follow = viewer.get('follow') or {}
    found.add(follow.get('match_id'))
    return found - {None, match_id}


class MatchProjection:
    def __init__(self, service, match):
        self.service, self.match = service, match
        self.live = LiveViewers()
        self.buckets = []  # The match's enabled audience buckets [{id, label}], from its catalogue.
        self.shared, self.presentation = None, None
        self.timeline = []  # (period, match seconds) per seq at the published snapshot: where a follow began.
        self.version, self.epoch = 0, str(uuid4())  # A new epoch tells clients to drop older versions.
        self.generation = 0  # Bumped by new narratives: same snapshot, new feed items.
        self._published_generation = -1
        self._refresh_lock = asyncio.Lock()
        self._task = asyncio.create_task(self._updates())

    async def close(self, code):
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        for peer in self.live.active():
            peer.close(code)

    async def _updates(self):
        while True:
            await self.match.changed.wait()
            self.match.changed.clear()
            if self.match.purged:
                return
            try:
                behind = await self.refresh()
            except RuleError as exc:
                if exc.code == 'match_not_found':
                    return
                # Upstream is still committing the newest events: keep the last consistent
                # state on screen and try again shortly.
                await asyncio.sleep(0.5)
                self.match.changed.set()
            except Exception:
                # One failed upstream read keeps the last consistent state and its sockets.
                log.warning('Projection of %s unavailable', self.match.match_id, exc_info=True)
                await asyncio.sleep(1)
                self.match.changed.set()
            else:
                if behind:  # ETL has not committed every received event yet.
                    await asyncio.sleep(0.5)
                    self.match.changed.set()

    async def refresh(self):
        """Publish the newest snapshot; True while it is behind this service's received events."""
        service, match = self.service, self.match
        async with self._refresh_lock:
            generation = self.generation
            payload = await service.match_data.capture(match)
            snapshot = payload.snapshot
            self.presentation = await service.config.get('presentation')
            # A /dev/ template edit reaches connected viewers: new choices, or a reconnect if theirs went.
            catalog, _ = await service.audiences.read(match.match_id)
            buckets = [{'id': b['id'], 'label': bucket_label(catalog['layers'], b['selections'], payload.teams)}
                       for b in catalog['buckets'] if b['enabled']]
            fresh = not (self.shared and self.shared['snapshot_id'] == snapshot.id
                         and generation == self._published_generation)
            if not fresh:
                stats, items, events = self.shared['stats'], self.shared['narratives'], self.shared['events']
                follow_items, moments = self.shared['follow_narratives'], self.shared['key_moments']
                playlists, clip_reels = self.shared['follow_playlists'], self.shared['moment_playlists']
                score = {t['id']: t.get('score') for t in self.shared['match']['teams']}
            else:
                stats = (await service.match_data.stats(snapshot))['stats']
                score = await service.match_data.score(snapshot, [t['id'] for t in payload.teams])
                closed = match.closed_through(snapshot.seq)
                items = await asyncio.to_thread(service.engine_narratives.items, snapshot, closed,
                                                self.presentation.narratives_per_bucket)
                follow_items = await asyncio.to_thread(service.subscriptions.narratives, snapshot, closed)
                final = ((match.info or {}).get('capabilities') or {}).get('periods', 2)
                facts = await service.match_data.key_moments(snapshot)
                moments = feed_moments(facts, await service.config.get('key-moment-feed'), payload.teams,
                                       payload.players, final)
                playlists, clip_reels = await self._playlists(snapshot, facts, moments)
                names = {p['id']: p['name'] for p in payload.players}
                teams = {t['id']: t['name'] for t in payload.teams}
                events = [{**e.model_dump(mode='json', exclude=set(DETAIL_FIELDS)),
                           'team_name': teams.get(e.team_id), 'player_name': names.get(e.player_id)}
                          for e in observed(payload.events[-RECENT_DELIVERIES:])[-30:]]
                self.timeline = [(e.period, e.match_time_seconds) for e in payload.events]
                self._published_generation = generation
            async with match.guard():
                self.version += 1
                teams = [{**team, 'score': score.get(team['id'])} for team in payload.teams]
                video = bool(((match.info or {}).get('capabilities') or {}).get('video'))
                self.shared = {'type': 'snapshot', 'version': self.version,
                    'synthetic': match.synthetic,
                    'snapshot_id': snapshot.id, 'projection_epoch': self.epoch, 'mode': service.questions.mode,
                    'match': {'id': match.match_id, 'fixture': match.fixture, 'status': match_status(match, payload.events),
                              'scheduled_kickoff': (match.info or {}).get('scheduled_kickoff'), 'seq': snapshot.seq, 'clock_seconds': snapshot.clock_seconds, 'period': snapshot.period,
                              'teams': teams,
                              'media': {'url': service.media_url(match.match_id) if video else None,
                                        'seconds': snapshot.video_seconds}},
                    'events': events, 'narratives': items, 'stats': stats,
                    'follow_narratives': follow_items, 'follow_playlists': playlists, 'moment_playlists': clip_reels,
                    'key_moments': moments,
                    'calculations': match.calculations(snapshot.seq)}
                self.buckets, enabled = buckets, {b['id'] for b in buckets}
                for peer in self.live.active():
                    chosen = (peer.viewer.get('audience') or {}).get('bucket_id')
                    if chosen not in enabled and (chosen or enabled):
                        peer.close(1013)  # The reconnect picks an enabled bucket.
                    else:
                        peer.offer(self.compose(peer.viewer))
                behind = snapshot.seq < match.seq
        if fresh:  # viewers of other matches who follow or pinned from this one see it move
            service.cross_changed(match.match_id)
        return behind

    async def _playlists(self, snapshot, facts, moments):
        """({topic_id: replay}, {bucket_id: replay}): each followed topic's moment clips and each bucket's key-event
        clips at the snapshot (services/follow_clips)."""
        service, match = self.service, self.match
        config = (await service.config.get('subscriptions')).clips
        follows = service.subscriptions  # bucket clips need no follows
        topics, buckets = await asyncio.gather(
            asyncio.to_thread(follows.clips, snapshot, config.max_items) if follows else asyncio.sleep(0, {}),
            asyncio.to_thread(service.engine_narratives.clips, snapshot, config.max_items))
        if not topics and not buckets:
            return {}, {}
        video = bool(((match.info or {}).get('capabilities') or {}).get('video'))
        args = ({m['id']: m for m in moments}, await service.match_data.periods(snapshot), snapshot.video_seconds,
                await service.config.get('replay-timing'), config,
                service.media_url(match.match_id) if video else None)
        return moment_playlists(topics, facts, *args), moment_playlists(buckets, facts, *args)

    def compose(self, viewer):
        shared, profile, config = self.shared, viewer['profile'], self.presentation
        teams = shared['match']['teams']
        support = profile.get('team') if profile.get('team') in {t['id'] for t in teams} else 'neutral'
        # Narratives route by the chosen bucket id only.
        bucket_id = (viewer['audience'] or {}).get('bucket_id')
        routing_ids = {bucket_id} if bucket_id else set()
        pins = {o['calculation_id']: o for o in viewer['offers'] if o.get('calculation_id')}
        available = {s['id']: s for s in shared['stats']}
        tracked = []
        for identifier, offer in list(pins.items())[-config.card_slots:]:
            if split_pin_id(identifier)[1]:
                tracked.append(self.service.cross_card(identifier, offer))
            elif offer.get('kind') == 'comparison':
                tracked.append({**comparison_card(offer, shared['calculations'], available), 'pinned': True, 'pin_id': identifier})
            elif offer.get('kind') == 'standard':
                stat_id = offer['standard_stat_id']
                stat = available.get(stat_id, {'id': stat_id, 'label': offer['label'], 'value': None, 'available': False,
                                               'complete': False, 'unavailable_reason': 'Not in the stat catalogue.'})
                tracked.append({**stat, 'kind': 'standard', 'pinned': True, 'pin_id': identifier})
            elif identifier in shared['calculations']:
                tracked.append({**shared['calculations'][identifier], 'kind': 'custom',
                                'pinned': True, 'pin_id': identifier})
            elif offer.get('unsupported'):
                # A rule with no SPADL equivalent: shown, never counted.
                tracked.append({'id': identifier, 'label': offer['label'], 'value': None, 'available': False,
                                'complete': False, 'unavailable_reason': offer['unsupported'], 'kind': 'custom',
                                'pinned': True, 'pin_id': identifier})
        stat_ids = config.default_stats.resolve(support)
        pinned_standard = {card['id'] for card in tracked if card['kind'] == 'standard'}
        if any(i in available and not available[i].get('available', True) for i in stat_ids):
            stat_ids = [*stat_ids, *config.fallback_stats.resolve(support)]
        defaults = [paired(available[i], available, teams) for i in dict.fromkeys(stat_ids)
                    if i in available and available[i].get('available', True) and i not in pinned_standard
                    and i not in config.excluded_stats]
        # Tracked stats displace the lowest-priority defaults, never a protected kind.
        shown = defaults[:config.card_slots]
        protected = lambda card: card['id'].split(':', 1)[-1] in config.protected_stat_kinds
        keep = {c['id'] for c in sorted(shown, key=lambda c: not protected(c))[:config.card_slots - len(tracked)]}
        # Feed rules (contracts §8b): a follower sees only the followed topic's narratives for their bucket, others
        # their bucket's insights; everyone sees the pivotal key moments.
        follow = viewer.get('follow')
        source, follow_match, origin = shared, None, self
        if follow and follow.get('match_id') not in (None, self.match.match_id):
            # A follow of another live match: its narratives and clips at that match's own position,
            # written for the follow's bucket of that match, marked with that match's header.
            other = self.service.projections.get(follow['match_id'])
            source, origin = (other and other.shared) or {}, other
            follow_match = header_of(source['match']) if source else None
            routing_ids = {follow['bucket_id']}
        if follow:
            # Where the viewer began following, on the followed match's clock: catch-up above, live below.
            timeline, seq = (origin.timeline if origin else []), follow.get('since_seq') or 0
            if timeline and seq:
                period, seconds = timeline[min(seq, len(timeline)) - 1]
                follow = {**follow, 'since_period': period, 'since_clock_seconds': seconds}
            narratives = [{**n, 'other_match': follow_match} if follow_match else n
                          for n in source.get('follow_narratives', [])
                          if n['topic_id'] == follow['topic_id'] and routing_ids.intersection(n['buckets'])]
        else:
            narratives = [n for n in shared['narratives'] if routing_ids.intersection(n['buckets'])]
        return {key: shared[key] for key in ('type', 'version', 'projection_epoch', 'synthetic', 'mode', 'match', 'events')} | {
            'snapshot_id': shared['snapshot_id'], 'profile': profile, 'audience': viewer['audience'],
            'audience_buckets': self.buckets, 'bucket_id': bucket_id, 'cards': [c for c in shown if c['id'] in keep] + tracked,
            'feed_mode': 'following' if follow else 'insights', 'follow': follow, 'narratives': narratives,
            # A follower's moment clips: one playlist for the followed topic.
            'follow_playlist': source.get('follow_playlists', {}).get(follow['topic_id']) if follow else None,
            # Everyone else: the key-event clips of their bucket's shared narratives.
            'moment_playlist': None if follow else shared.get('moment_playlists', {}).get(bucket_id),
            'follow_match': follow_match,
            'key_moments': shared.get('key_moments', [])}


def comparison_card(offer, calculations, available):
    """Two live team values occupy one viewer card."""
    sides = []
    for side in offer['sides']:
        result = (available.get(side['standard_stat_id'], {}) if side.get('kind') == 'standard'
                  else calculations.get(pin_id(side), {}))
        value = result.get('value') if result.get('available', True) and result.get('complete', True) else None
        sides.append({'team_id': side['team_id'], 'name': side['name'], 'value': value})
    return {'id': pin_id(offer), 'kind': 'custom', 'label': offer['label'], 'unit': offer.get('unit', ''),
            'value': None, 'sides': sides}


def paired(stat, available, teams):
    """A default card shows its kind for both teams (home, then away) in one slot: `sides` carries each team's value
    from the catalogue (None when that team's row is missing or incomplete); `value` stays the resolved stat's own."""
    kind = stat['id'].split(':', 1)[-1]
    sides = []
    for team in teams:
        row = available.get(f"{team['id']}:{kind}")
        shown = row if row and row.get('available', True) and row.get('complete', True) else None
        sides.append({'team_id': team['id'], 'name': team.get('name'), 'value': shown['value'] if shown else None})
    label = stat['label'].removeprefix('Both teams ')
    for team in teams:
        if team.get('name'):
            label = label.removeprefix(team['name'] + ' ')
    return {**stat, 'label': label[:1].upper() + label[1:], 'kind': 'standard', 'sides': sides}


class ProductService:
    def __init__(self, questions, registry, audiences, engine_narratives, config, match_data, dab, media=None,
                 subscriptions=None):
        self.questions, self.registry, self.audiences = questions, registry, audiences
        self.subscriptions = subscriptions  # repositories/subscriptions.SubscriptionRepository
        self.engine_narratives, self.config, self.match_data, self.dab = engine_narratives, config, match_data, dab
        self.media = media
        self.projections = {}
        self._locks = KeyedLocks()  # Per match: one match's sessions never wait for another's.
        questions.session_started = self._replace_profile
        registry.on_purge.append(self._purged)

    def media_url(self, match_id):
        return self.media.stream_url(match_id) if self.media else stream_path(match_id)

    def projection(self, match_id):
        match = self.registry.get(match_id)
        projection = self.projections.get(match_id)
        if projection is None:
            projection = self.projections[match_id] = MatchProjection(self, match)
        return projection

    def cross_changed(self, match_id):
        """`match_id` published new data: refresh the matches whose viewers follow or pinned from it."""
        for projection in self.projections.values():
            if projection.match.match_id != match_id and any(
                    match_id in sources(peer.viewer, projection.match.match_id) for peer in projection.live.active()):
                projection.match.changed.set()

    def cross_card(self, identifier, offer):
        """A pinned stat from another live match, at that match's own position and marked with its header."""
        base, source = split_pin_id(identifier)
        projection = self.projections.get(source)
        shared = projection and projection.shared
        card = {'id': identifier, 'label': offer['label'], 'value': None, 'available': False, 'complete': False,
                'unavailable_reason': 'That match is no longer live.'}
        if shared:
            if offer.get('kind') == 'comparison':
                stat = comparison_card(offer, shared['calculations'], {s['id']: s for s in shared['stats']})
            elif offer.get('kind') == 'standard':
                stat = next((s for s in shared['stats'] if s['id'] == offer['standard_stat_id']), None)
            else:
                stat = shared['calculations'].get(base)
            card = {**card, **(stat or {'unavailable_reason': 'Not available in that match yet.'}), 'id': identifier,
                    'other_match': header_of(shared['match'])}
        return {**card, 'kind': 'standard' if offer.get('kind') == 'standard' else 'custom', 'pinned': True,
                'pin_id': identifier}

    async def close(self):
        for projection in list(self.projections.values()):
            await projection.close(1001)
        self.projections.clear()

    async def _purged(self, match_ids):
        for match_id in match_ids:
            if projection := self.projections.pop(match_id, None):
                await projection.close(4404)
        self.audiences.forget(match_ids)
        # Viewers of other matches who followed a purged match (the purge deleted the follow) go back to Insights;
        # their pins from it say unavailable.
        gone = set(match_ids)
        for projection in self.projections.values():
            peers = [p for p in projection.live.active() if gone & sources(p.viewer, projection.match.match_id)]
            for peer in peers:
                if (peer.viewer.get('follow') or {}).get('match_id') in gone:
                    peer.viewer = {**peer.viewer, 'follow': None}
            if peers:
                projection.match.changed.set()

    async def narrative(self, narrative):
        """One engine message (a bucket insight, a followed topic's narrative or moment clip); kept only for a
        known, unpurged match (and a known topic)."""
        match = self.registry.matches.get(narrative.matchId)
        if match is None or match.purged:
            return False
        if isinstance(narrative, EngineFollowClip):
            store = self.subscriptions.save_clip
        elif isinstance(narrative, EngineMomentClip):
            store = self.engine_narratives.save_clip
        else:
            store = self.subscriptions.save_narrative if narrative.kind == 'subscription' else self.engine_narratives.save
        if not await asyncio.to_thread(store, narrative):
            return False
        if projection := self.projections.get(narrative.matchId):
            projection.generation += 1
        match.changed.set()
        return True

    async def matches(self):
        """Known matches with ETL's status and progress: live, then scheduled by kickoff, then finished."""
        ids = list(self.registry.matches)
        try:
            infos, marks = await asyncio.gather(self.dab.matches(ids), self.dab.watermarks(ids))
        except Exception as exc:
            raise RuleError('matches_unavailable', 'The match list is temporarily unavailable.', 503) from exc
        scores = dict(zip(infos, await asyncio.gather(*(self._score(i, marks.get(i, {'seq': 0}), infos[i]['teams']) for i in infos))))
        rows = []
        for match_id, info in infos.items():
            mark = marks.get(match_id, {'seq': 0})
            video = bool((info.get('capabilities') or {}).get('video'))
            rows.append({'match_id': match_id, 'fixture': info['fixture'], 'status': info['status'],
                         'scheduled_kickoff': info['scheduled_kickoff'], 'description': info['description'],
                         'seq': mark['seq'], 'period': mark.get('period'), 'clock_seconds': mark.get('clock_seconds'),
                         'teams': [{**{k: t[k] for k in ('id', 'position', 'name', 'short_name', 'code', 'branding')},
                                    'score': scores[match_id].get(t['id'])} for t in info['teams']],
                         'video': {'hls': self.media_url(match_id)} if video else None})
        return sorted(rows, key=lambda r: (STATUS_ORDER[r['status']],
                                           r['scheduled_kickoff'] or '' if r['status'] == 'scheduled' else ''))

    async def _score(self, match_id, mark, teams):
        """Goals per contestant (MA3 goals and VAR decisions) at the snapshot ETL and this service have reached."""
        match = self.registry.matches.get(match_id)
        if match is None:
            return {}
        snapshot = MatchSnapshot.at(match_id, min(mark['seq'], match.seq))
        try:
            return await self.match_data.score(snapshot, [t['id'] for t in teams])
        except RuleError:
            return {}

    async def _replace_profile(self, match_id, profile_id, viewer_id=''):
        if projection := self.projections.get(match_id):
            projection.live.replace_profile(profile_id, viewer_id)

    async def detach(self, match_id, peer):
        if projection := self.projections.get(match_id):
            projection.live.detach(peer)

    async def _viewer(self, match_id, token):
        row = await self.questions.read(match_id, token)
        account = await self.questions.profile(row['profile_id'])
        projection = self.projection(match_id)
        info = await self.match_data.info(projection.match)
        catalog, _ = await self.audiences.read(match_id)
        enabled = [b for b in catalog['buckets'] if b['enabled']]
        projection.buckets = [{'id': b['id'], 'label': bucket_label(catalog['layers'], b['selections'], info['teams'])}
                              for b in enabled]
        # The viewer's choice while enabled, else the first bucket sharing most account defaults.
        chosen = (row.get('audience') or {}).get('bucket_id')
        bucket = next((b for b in enabled if b['id'] == chosen), None) or max(
            enabled, default=None, key=lambda b: sum(account['selections'].get(k) == v for k, v in b['selections'].items()))
        audience = bucket and {'bucket_id': bucket['id'], 'selections': bucket['selections']}
        label = bucket and next(b['label'] for b in projection.buckets if b['id'] == bucket['id'])
        follow = await asyncio.to_thread(self.subscriptions.active, token)
        for other_id in sources({**row, 'follow': follow}, match_id):
            with suppress(RuleError):  # a cleared match: its cards and follow show as gone
                if (other := self.projection(other_id)).shared is None:
                    other.match.changed.set()  # published without waiting for that match's next event
        return {**row, 'audience': audience, 'follow': follow,
                'profile': self._profile(projection.match, account, catalog['layers'],
                                         (audience or {}).get('selections') or account['selections'], label)}

    @staticmethod
    def _profile(match, account, layers, selections, label=None):
        """`team`: the contestant the selected options back (else `neutral`); the name is the bucket's label."""
        side = supported_side(layers, selections)
        team = next((t for t in match.info['teams'] if side and t.get('position') == side), None)
        return {'id': account['id'], 'display_name': label or account['display_name'], 'selections': selections,
                'team': team['id'] if team else 'neutral'}

    async def profiles(self):
        return await self.questions.profiles()

    async def prices(self):
        """Viewer receipt prices (configuration), with the config table's ETag."""
        document, etag = await self.config.document('prices')
        return {**document['value'], 'revision': document['revision']}, etag

    async def start(self, match_id, profile_id, viewer_id=''):
        async with self._locks(match_id):
            row = await self.questions.start(match_id, profile_id, viewer_id)
            return await self.bootstrap(match_id, row['session_token'])

    async def bootstrap(self, match_id, token):
        viewer = await self._viewer(match_id, token)
        projection = self.projection(match_id)
        if projection.shared is None:
            try:
                await projection.refresh()
            except RuleError:
                raise
            except Exception as exc:
                raise RuleError('snapshot_unavailable', 'Live match data is temporarily unavailable.', 503) from exc
        return {**viewer, 'snapshot': projection.compose(viewer)}

    @staticmethod
    def _subscription(viewer):
        # Live delivery retains routing/pin IDs, never the viewer's chat transcript.
        return {key: viewer[key] for key in ('match_id', 'profile_id', 'viewer_id', 'profile', 'audience', 'follow') if key in viewer} | {
            'offers': [{key: offer[key] for key in ('calculation_id', 'kind', 'standard_stat_id', 'label', 'unsupported', 'sides', 'unit')
                        if key in offer} for offer in viewer['offers'] if offer.get('calculation_id')]}

    async def attach(self, match_id, token):
        async with self._locks(match_id), self.questions.session_guard(match_id):
            data = await self.bootstrap(match_id, token)
            projection = self.projection(match_id)
            return projection.live.attach(str(token), self._subscription(data)), data['snapshot']

    async def select_audience(self, match_id, token, choice):
        async with self._locks(match_id), self.questions.session_guard(match_id):
            await self.bootstrap(match_id, token)
            catalog, _ = await self.audiences.read(match_id)
            bucket = next((b for b in catalog['buckets'] if b['id'] == choice.bucket_id and b['enabled']), None)
            if bucket is None:
                raise RuleError('audience_unavailable', 'This audience is not available for the match.', 422)
            projection = self.projection(match_id)
            async with projection._refresh_lock:
                async with projection.match.guard():
                    await asyncio.to_thread(self.questions.repository.set_audience, token,
                                            {'bucket_id': bucket['id'], 'selections': bucket['selections']})
                    await asyncio.to_thread(self.subscriptions.audience_changed, token)
                viewer = await self._viewer(match_id, token)
                projection.live.update(str(token), self._subscription(viewer))
                return {**viewer, 'snapshot': self._publish(projection, token, viewer)}

    async def viewer(self, match_id, token):
        return await self._viewer(match_id, token)

    async def republish(self, match_id, token):
        """After a follow change: this viewer's new snapshot (feed mode and narratives), pushed to its socket."""
        async with self._locks(match_id):
            viewer = await self._viewer(match_id, token)
            projection = self.projection(match_id)
            if projection.shared is None:
                await projection.refresh()
            projection.live.update(str(token), self._subscription(viewer))
            return self._publish(projection, token, viewer)

    @staticmethod
    def _publish(projection, token, viewer):
        """Yield-free, like refresh: an older queued snapshot cannot undo this change."""
        projection.version += 1
        projection.shared['version'] = projection.version
        snapshot = projection.compose(viewer)
        if peer := projection.live.peers.get(str(token)):
            peer.offer(snapshot)
        return snapshot

    async def track(self, match_id, token, offer_id):
        async with self._locks(match_id):
            viewer = await self._viewer(match_id, token)
            projection = self.projection(match_id)
            slots = (await self.config.get('presentation')).card_slots
            offer = next((o for o in viewer['offers'] if o['id'] == str(offer_id)), None)
            if offer is None:
                raise RuleError('offer_not_found', 'This offer is not in your conversation.', 404)
            if offer.get('unsupported'):
                raise RuleError('unavailable_measurement', offer['unsupported'], 422)
            identifier = viewer_pin_id(offer, match_id)
            pins = {o['calculation_id'] for o in viewer['offers'] if o.get('calculation_id')}
            if identifier not in pins and len(pins) >= slots:
                raise RuleError('cards_full', 'Remove a tracked stat before adding another.', 409)
            result = await self.questions.track(match_id, token, offer_id)
            viewer = await self._viewer(match_id, token)
            projection.live.update(str(token), self._subscription(viewer))
            await projection.refresh()
            return {**result, 'snapshot': projection.compose(viewer)}

    async def clear_questions(self, match_id, token):
        async with self._locks(match_id):
            await self.questions.clear(match_id, token)
            viewer = await self.bootstrap(match_id, token)
            projection = self.projection(match_id)
            projection.live.update(str(token), self._subscription(viewer))
            return viewer

    async def untrack(self, match_id, token, calculation_id):
        async with self._locks(match_id):
            await self.questions.read(match_id, token)
            projection = self.projection(match_id)
            async with projection.match.guard():
                await asyncio.to_thread(self.questions.repository.untrack, token, calculation_id)
            viewer = await self._viewer(match_id, token)
            projection.live.update(str(token), self._subscription(viewer))
            if projection.shared is None:
                raise RuleError('snapshot_unavailable', 'Live match data is temporarily unavailable.', 503)
            return {'snapshot': self._publish(projection, token, viewer)}

    def score(self, match_id):
        """The published teams and ETL goal counts for the lab header."""
        projection = self.projections.get(match_id)
        match = projection and projection.shared and projection.shared['match']
        if not match:
            return None
        return [{'id': t['id'], 'name': t['name'], 'score': t.get('score')} for t in match['teams']]

