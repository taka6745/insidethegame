"""Story follows: the follow chat (planner + rule-based entity resolution), deterministic suggestions, follow and
unfollow (one active follow per viewer), and the engine's subscription-targets document. Reads are bounded by the
viewer's snapshot; a cross-match follow (PLAN.md §10.2) reads the followed match at its own position."""
import asyncio
import hashlib
import json
import logging
import time

from backend.adapters.usage import as_dict as usage_dict, start_usage
from backend.domain import RuleError
from backend.models.subscriptions import FollowSpec
from backend.models.viewer_audience import supported_side
from .cross_match import header
from .key_moments import feed_moments
from .names import match_score, rarity, words  # noqa: F401 (re-exported for tests)

log = logging.getLogger(__name__)
NO_MODEL = 'The follow chat is unavailable: no model is configured for this service. Use a suggestion instead.'


def resolve(kind, subject, teams, players, storylines, threshold, limit):
    """(spec fields, candidates): the single best entity for `subject`, trying `kind` first, then the other kinds.
    Words are weighted by rarity across every entity of the match. Ties or nothing above `threshold` return up to
    `limit` candidates (best first) instead."""
    pools = {'team': [({'kind': 'team', 'team_id': t['id']}, t['name'],
                       (t['name'], t.get('short_name'), t.get('code'), *(t.get('known_names') or ()))) for t in teams],
             'player': [({'kind': 'player', 'player_id': p['id'], 'team_id': p['team_id']}, p['name'], (p['name'],))
                        for p in players],
             'storyline': [({'kind': 'storyline', 'storyline_id': s['id']}, s['label'], (s['label'],))
                           for s in storylines if s['status'] != 'resolved']}
    weight = rarity([names for pool in pools.values() for _, _, names in pool])
    for pool in [kind, *(k for k in pools if k != kind)] if kind in pools else list(pools):
        scored = sorted(((match_score(subject, names, weight), fields, name) for fields, name, names in pools[pool]),
                        key=lambda row: -row[0])
        scored = [row for row in scored if row[0] >= threshold]
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            return {**scored[0][1], 'label': scored[0][2]}, []
        if scored:
            return None, [{**fields, 'label': name} for _, fields, name in scored[:limit]]
    return None, []


class SubscriptionService:
    def __init__(self, repository, questions, registry, match_data, narratives, config, product, planner=None,
                 cross=None):
        self.repository, self.questions, self.registry = repository, questions, registry
        self.cross = cross  # services/cross_match.CrossMatch: follows of the demo's other matches
        self.match_data, self.narratives, self.config, self.product = match_data, narratives, config, product
        self.planner = planner  # agents/subscription_planner.SubscriptionPlanner, None without a model

    async def _context(self, match_id, seq=None):
        """(snapshot, teams, players, storylines) as the viewer's snapshot knows them."""
        match = self.registry.get(match_id)
        payload = await self.match_data.capture(match, seq)
        storylines = []
        if hasattr(self.narratives, 'storylines'):
            try:
                storylines = await self.narratives.storylines(payload.snapshot)
            except Exception:
                log.warning('Storylines of %s unavailable', match_id)
        return payload.snapshot, payload.teams, payload.players, storylines

    async def listing(self, match_id, token):
        row = await self.questions.read(match_id, token)
        follow, follows = await asyncio.to_thread(self.repository.listing, token)
        return {'follow': follow, 'follows': follows, 'turns': row['follow_turns']}

    def validate(self, spec, teams, players, storylines):
        """The spec's ids exist in this match at the snapshot (a storyline must still be open)."""
        team_ids, player_teams = {t['id'] for t in teams}, {p['id']: p['team_id'] for p in players}
        if spec.team_id is not None and spec.team_id not in team_ids:
            raise RuleError('unknown_team', 'That team is not in this match.', 422)
        if spec.player_id is not None:
            if spec.player_id not in player_teams:
                raise RuleError('unknown_player', 'That player is not in this match.', 422)
            if spec.team_id not in (None, player_teams[spec.player_id]):
                raise RuleError('unknown_player', 'That player is not in that team.', 422)
            spec = spec.model_copy(update={'team_id': player_teams[spec.player_id]})
        if spec.storyline_id is not None:
            line = next((s for s in storylines if s['id'] == spec.storyline_id), None)
            if line is None:
                raise RuleError('unknown_storyline', 'That story has not started in this match yet.', 422)
            if line['status'] == 'resolved':
                raise RuleError('storyline_resolved', 'That story has already ended.', 422)
        return spec

    async def follow(self, match_id, token, spec, seq=None, target=None):
        """Follow `spec` at the viewer's snapshot. One active follow per viewer: following the same topic again
        returns it; a different one is 409 follow_limit (unfollow first). `target`: another live match of the demo
        (a cross-match follow), validated and started at that match's own position, written for a bucket of its
        own catalogue."""
        viewer = await self.product.viewer(match_id, token)
        bucket_id = None
        if target not in (None, match_id):
            if self.cross is None:
                raise RuleError('match_not_found', 'That match is not part of this demo.', 404)
            await self.cross.other(match_id, target)
            snapshot, teams, players, storylines = await self._context(target)
            bucket_id = await self._bucket(target, viewer)
        else:
            target = match_id
            snapshot, teams, players, storylines = await self._context(match_id, seq)
        spec = self.validate(spec, teams, players, storylines)
        limits = (await self.config.get('subscriptions')).limits
        # The followed match's guard: its purge cannot interleave with the insert (a follow of a match purged
        # after the checks above is 404, never a row without its topic).
        async with self.registry.get(target).guard():
            follow, created = await asyncio.to_thread(
                self.repository.follow, token, target, spec.model_dump(mode='json'), spec.topic_id(target),
                snapshot.seq, viewer['audience'], limits.follow_changes_per_minute, bucket_id)
        return {'follow': follow, 'created': created, 'snapshot': await self.product.republish(match_id, token)}

    async def _bucket(self, target, viewer):
        """The bucket of `target`'s catalogue a cross-match follow is written for: an enabled one backing neither
        team when any is (the viewer's side names a position in their own match), sharing most of the viewer's other
        choices."""
        catalog, _ = await self.product.audiences.read(target)
        enabled = [b for b in catalog['buckets'] if b['enabled']]
        if not enabled:
            raise RuleError('audience_unavailable', 'That match has no audience enabled.', 422)
        mine = (viewer['audience'] or {}).get('selections') or {}
        return max(enabled, key=lambda b: (supported_side(catalog['layers'], b['selections']) is None,
                                           sum(mine.get(k) == v for k, v in b['selections'].items())))['id']

    async def unfollow(self, match_id, token, subscription_id):
        await self.questions.read(match_id, token)
        limits = (await self.config.get('subscriptions')).limits
        ended = await asyncio.to_thread(self.repository.unfollow, token, subscription_id, limits.follow_changes_per_minute)
        return {'follow': None, 'ended': ended, 'snapshot': await self.product.republish(match_id, token)}

    async def suggestions(self, match_id, token, seq=None):
        """Ready-to-follow specs, by rule: open storylines by salience, players in the key moments so far, then
        the teams (the viewer's team first); the viewer's current follow is left out."""
        viewer = await self.product.viewer(match_id, token)
        config = (await self.config.get('subscriptions')).suggestions
        snapshot, teams, players, storylines = await self._context(match_id, seq)
        items = []
        if config.storylines:
            items += [{'kind': 'storyline', 'storyline_id': s['id'], 'label': s['label'][:80]}
                      for s in sorted(storylines, key=lambda s: -s['salience'])
                      if s['status'] != 'resolved' and s['salience'] >= config.min_storyline_salience]
        if config.players:
            facts = await self.match_data.key_moments(snapshot)
            moment_config = await self.config.get('key-moment-feed')
            names = {p['id']: p for p in players}
            for moment in reversed(feed_moments(facts, moment_config, teams, players)):
                if moment['player_id'] in names:
                    p = names[moment['player_id']]
                    items.append({'kind': 'player', 'player_id': p['id'], 'team_id': p['team_id'], 'label': p['name'][:80]})
        if config.teams:
            mine = viewer['profile']['team']
            items += [{'kind': 'team', 'team_id': t['id'], 'label': t['name'][:80]}
                      for t in sorted(teams, key=lambda t: t['id'] != mine)]
        if self.cross and (cross := await self.cross.settings()).enabled and cross.suggest_teams:
            for other in self.cross.others(match_id):
                info = await self.cross.info_of(other)
                items += [{'kind': 'team', 'team_id': t['id'], 'label': t['name'][:80], 'match_id': other.match_id,
                           'other_match': header(other, info)} for t in (info or {}).get('teams', [])]
        current = (viewer.get('follow') or {}).get('topic_id')
        out, seen = [], {current}
        for item in items:
            option = self._option(match_id, item)
            if option['id'] not in seen:
                seen.add(option['id'])
                out.append(option)
        return {'snapshot_id': snapshot.id, 'items': out[:config.max_items]}

    async def chat(self, match_id, token, request_id, prompt, seq=None):
        """One follow-chat turn: the planner's draft, its subject resolved to ids by rule. A follow is only
        proposed (`proposal`); the viewer confirms it with POST follows."""
        if self.planner is None:
            raise RuleError('model_unavailable', NO_MODEL, 503)
        row = await self.questions.read(match_id, token)
        config = await self.config.get('subscriptions')
        turn = await asyncio.to_thread(self.questions.repository.begin, token, request_id, prompt, 'follow',
                                       config.limits.planner_turns_per_minute)
        if turn['status'] != 'pending':
            return turn['reply']
        if not turn['created']:
            raise RuleError('question_busy', 'Please wait for the current answer.', 409)
        started, usage = time.perf_counter(), start_usage()
        try:
            snapshot, teams, players, storylines = await self._context(match_id, seq)
            follow = await asyncio.to_thread(self.repository.active, token)
            # The planner also knows the other live matches' teams and squads, so "follow City's pressing" or
            # "follow Edlund" can be proposed there.
            other_teams, other_players = await self._other_entities(match_id)
            here = self.registry.get(match_id)
            live = await self.cross.listing(here, snapshot) if self.cross else []
            draft = await self.planner.plan(prompt, teams=[*teams, *other_teams],
                                            players=[*players, *other_players], storylines=storylines,
                                            follow=follow, live_matches=live,
                                            turns=row['follow_turns'][-config.limits.planner_context_turns:])
            reply = {'status': 'answer', 'text': draft.reply, 'proposal': None, 'candidates': []}
            if draft.action == 'unfollow':
                reply['status'] = 'unfollow' if follow else 'answer'
            elif draft.action in ('follow', 'clarify'):
                found, candidates, focus = None, [], draft.focus.strip()
                if draft.kind == 'theme':
                    focus = focus or (draft.subject or '').strip()
                    found = {'kind': 'theme', 'label': focus} if focus else None
                elif draft.subject:
                    found, candidates = resolve(draft.kind, draft.subject, teams, players, storylines,
                                                config.min_name_match, config.max_candidates)
                    if not found and not candidates:
                        found = await self._elsewhere(match_id, draft, config)
                if found:
                    found = {**found, 'focus': focus, 'label': (draft.label or found['label']).strip()[:80]}
                    if draft.action == 'follow':
                        reply['proposal'] = self._option(match_id, found)
                    else:
                        candidates = [found]
                if draft.action == 'clarify' and draft.options:
                    # The planner's drill-in choices, each resolved to a real entity by rule (or a theme in the
                    # viewer's words); unresolved ones are dropped, so chips never name what is not there.
                    choices = [c for c in [await self._choice(match_id, o, teams, players, storylines, config)
                                           for o in draft.options] if c]
                    candidates = choices or candidates
                reply['status'] = 'proposal' if reply['proposal'] else 'clarify'
                reply['candidates'] = [self._option(match_id, c) for c in candidates]
            reply.update(snapshot=snapshot.model_dump(mode='json'), usage=usage_dict(usage, time.perf_counter() - started))
            match = self.registry.get(match_id)
            async with match.guard():
                await asyncio.to_thread(self.questions.repository.finish, token, turn['id'], reply)
            return reply
        except BaseException as exc:
            failure = None if isinstance(exc, (RuleError, asyncio.CancelledError)) else {
                'status': 'unsupported', 'text': 'Sorry, I could not work that out. Please try again.',
                'proposal': None, 'candidates': [], 'usage': usage_dict(usage, time.perf_counter() - started)}
            try:
                await asyncio.shield(asyncio.to_thread(self.questions.repository.fail, token, turn['id'], failure))
            except RuleError:
                pass
            if failure is None:
                raise
            log.warning('Follow chat turn %s failed: %s', turn['id'], type(exc).__name__)
            return failure

    async def _choice(self, match_id, option, teams, players, storylines, config):
        """One clarify option as follow fields, or None when its subject names nothing in the live matches."""
        focus, label = option.focus.strip(), option.label.strip()[:80]
        if option.kind == 'theme':
            return {'kind': 'theme', 'label': label, 'focus': focus or label}
        if not option.subject:
            return None
        found, _ = resolve(option.kind, option.subject, teams, players, storylines, config.min_name_match, 1)
        if not found:
            found = await self._elsewhere(match_id, option, config)
        return {**found, 'focus': focus, 'label': label} if found else None

    async def _other_entities(self, match_id):
        """(teams, players) of the demo's other live matches (their match info: names and squads)."""
        if self.cross is None or not (await self.cross.settings()).enabled:
            return [], []
        infos = [info for other in self.cross.others(match_id) if (info := await self.cross.info_of(other))]
        return [t for info in infos for t in info['teams']], [p for info in infos for p in info['players']]

    async def _elsewhere(self, match_id, draft, config):
        """The draft's subject in another live match of the demo (at its own position), or None."""
        if self.cross is None or not (await self.cross.settings()).enabled:
            return None
        hits = []
        for other in self.cross.others(match_id):
            try:
                _, teams, players, storylines = await self._context(other.match_id)
                info = await self.match_data.info(other)
            except RuleError:
                continue
            found, _ = resolve(draft.kind, draft.subject, teams, players, storylines, config.min_name_match, 1)
            if found:
                hits.append((found, other, info))
        if not hits:
            return None
        # Each match resolves against its own names, so a shared word (a town two clubs share) can match in several: keep the
        # one whose name fits the subject best, weighting words by rarity across every match searched.
        weight = rarity([(f['label'],) for f, _, _ in hits])
        found, other, info = max(hits, key=lambda hit: match_score(draft.subject, (hit[0]['label'],), weight))
        return {**found, 'match_id': other.match_id, 'other_match': header(other, info)}

    @staticmethod
    def _option(match_id, fields):
        """A ready-to-follow option; `match_id` in `fields` names another live match of the demo."""
        target = fields.get('match_id') or match_id
        spec = FollowSpec.model_validate({k: v for k, v in fields.items() if k not in ('match_id', 'other_match')})
        option = {'id': spec.topic_id(target), 'label': spec.label, 'spec': spec.model_dump(mode='json')}
        return option if target == match_id else {**option, 'match_id': target, 'other_match': fields.get('other_match')}

    async def targets(self, match_id):
        """The engine's subscription-targets document and its ETag: the match's followed topics (most followed
        first, at most limits.max_topics_per_match) with their followers' buckets, plus the decision tunables."""
        self.registry.get(match_id)
        document, _ = await self.config.document('subscriptions')
        config = document['value']
        revision, rows = await asyncio.to_thread(self.repository.targets, match_id,
                                                 config['limits']['max_topics_per_match'])
        body = {'schema_version': 1, 'match_id': match_id, 'revision': revision,
                'config_revision': document['revision'],
                'decision': config['decision'], 'novelty': config['novelty'], 'prefilter': config['prefilter'],
                'limits': config['limits'], 'catch_up': config['catch_up'], 'clips': config['clips'],
                'topics': [{'topic_id': r['topic_id'], 'spec': r['spec'], 'created_seq': r['created_seq'],
                            'followers': r['followers'], 'buckets': sorted(r['buckets'] or [])} for r in rows]}
        return body, '"' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() + '"'
