"""One live match: its received canonical events (the clock) and custom calculations over SPADL actions.

Events arrive only from the stream (MatchEvent v2), in seq order; they give a snapshot its clock,
periods and the viewer's event ticker. Custom calculations count SPADL actions read from ETL GraphQL
up to the snapshot (finalSeq <= seq <= spadlSeq), never canonical events. Nothing here reads a recording."""
import asyncio
import bisect
import logging
import time

from backend.adapters.match_reference import data_reference
from backend.agents.conversation import assistant_message
from backend.domain import RuleError
from backend.models.actions import SpadlAction
from backend.models.events import Event
from backend.models.rules import Rule
from backend.services.filter_engine import FilterEngine
from backend.services.plan_conversations import PlanConversations
from backend.services.rule_availability import incomplete_player_rule, unsupported_reason

log = logging.getLogger(__name__)
MAX_PENDING = 20_000  # Out-of-order events held per match while a seq is missing.


class LiveMatch:
    def __init__(self, row, repository, *, max_calculations=10_000, dab=None):
        self.match_id, self.fixture = row['match_id'], row['fixture']
        self.repository, self.max_calculations = repository, max_calculations
        self.lock = asyncio.Lock()
        self.changed = asyncio.Event()  # Set on every committed change; projections wait on it.
        self.events = []  # Received canonical events; events[seq - 1].
        self.period_ends = []  # (seq, period) of received period_end events.
        self.engine, self.labels, self.values = FilterEngine(), {}, {}  # values: id -> [(final seq, value)]
        self.actions, self.actions_seq = [], 0  # Final SPADL actions read so far; every finalSeq <= actions_seq.
        self._unattributed_actions = []
        self._sync = asyncio.Lock()
        self.dab = dab  # ETL GraphQL (adapters/etl_dab.py): SPADL actions for custom calculations.
        self.last_changed = []
        self.conversations = PlanConversations()
        self.info = None  # ETL `matches` info (adapters/ma3.py), cached once read.
        self.purged = False
        self._stale = False
        self._loaded = 0  # Counts rebuilds, so a SPADL read that a rebuild overtook is not counted.
        self.pending = {}  # seq -> event received after a missing seq.
        self.gap_since = None  # Monotonic time the missing seq first blocked delivery.

    @property
    def seq(self):
        return len(self.events)

    async def load(self):
        """Rebuild from received events and saved calculations; SPADL actions are read again from ETL."""
        events, calculations = await asyncio.to_thread(self.repository.load, self.match_id)
        engine, labels = FilterEngine(), {}
        for row in calculations:
            result = engine.register(Rule.model_validate(row['rule']))
            engine.restore_version(result.calculation_id, max(row['result']['version'], 1))
            labels[result.calculation_id] = row['label']
        self.engine, self.labels = engine, labels
        self.actions, self.actions_seq, self._unattributed_actions = [], 0, []
        self.events, self.period_ends = [], []
        for seq, event in enumerate(events, 1):
            self._observe(seq, event)
        self.values = {r.calculation_id: [(0, r.value)] for r in engine.calculations}
        self._stale = False
        self._loaded += 1

    @property
    def home(self):
        return next((t['id'] for t in (self.info or {}).get('teams', []) if t.get('position') == 'home'), None)

    @property
    def synthetic(self):
        """MA1's synthetic flag (labelled synthetic until the match info is read)."""
        return bool((self.info or {}).get('synthetic', True))

    async def sync_actions(self, dab, seq):
        """Read final SPADL actions up to `seq` (<= ETL's spadlSeq) and count them into every calculation.
        Actions that do not continue the ones held (a gap, a repeat, or a failure part-way through counting)
        rebuild the match from the database and recount every action from ETL, once, instead of wedging it."""
        async with self._sync:
            attempt = 0
            while True:
                if seq <= self.actions_seq or self.purged or self.home is None:
                    return  # Coordinates are made team-relative, so the home team (match info) must be known.
                start, loaded = self.actions_seq, self._loaded
                rows = await dab.spadl_actions(self.match_id, start, seq)
                actions = [SpadlAction.from_row(row, self.match_id, self.home) for row in rows]
                async with self.lock:
                    if self.purged:
                        return
                    if loaded != self._loaded:
                        continue  # A rebuild (accept_batch after a failed write) reset the held actions meanwhile.
                    if actions and actions[0].action_id != len(self.actions) or \
                            any(b.action_id != a.action_id + 1 for a, b in zip(actions, actions[1:])):
                        log.warning('Match %s: SPADL actions (%s, %s] start at %s with %s held; recounting from ETL',
                                    self.match_id, start, seq, actions[0].action_id, len(self.actions))
                        if attempt:
                            raise RuntimeError(f'Match {self.match_id}: SPADL actions out of order after a recount')
                        attempt += 1
                        await self.load()
                        continue
                    try:
                        await self._count(actions, seq)
                    except BaseException:
                        await self.load()  # Counting stopped part-way: memory no longer matches the database.
                        raise
                    return

    async def _count(self, actions, seq):
        """Append in-order actions to the held ones and every calculation (caller holds `lock`)."""
        changed = {}
        for action in actions:
            self.actions.append(action)
            if action.player_id is None:
                self._unattributed_actions.append(action)
            for result in self.engine.ingest(action):
                changed[result.calculation_id] = result
                self.values.setdefault(result.calculation_id, []).append((action.final_seq, result.value))
        if changed:
            await asyncio.to_thread(self.repository.update_results, self.match_id,
                                    [r.model_dump(mode='json') for r in changed.values()])
            self.last_changed = list(changed)
        self.actions_seq = seq

    async def catch_up(self):
        """Sync to the newest snapshot ETL (its SPADL watermark) and this service have committed."""
        if self.dab is None or self.purged:
            return
        mark = (await self.dab.watermarks([self.match_id])).get(self.match_id, {'seq': 0})
        await self.sync_actions(self.dab, min(mark['seq'], mark.get('spadl_seq', 0), self.seq))

    def actions_at(self, seq):
        """Final actions a snapshot at seq may read (call after sync_actions(seq))."""
        index = bisect.bisect_right(self.actions, seq, key=lambda action: action.final_seq)
        return self.actions[:index]

    def reference(self):
        capabilities = (self.info or {}).get('capabilities')
        return data_reference(capabilities)

    def history(self, seq=None):
        """Received events up to seq (never past what was received)."""
        return self.events[:self.seq if seq is None else min(seq, self.seq)]

    async def accept(self, seq, event):
        return bool(await self.accept_batch([(seq, event)]))

    async def accept_batch(self, deliveries, gap=None):
        """Commit consecutive MatchEvents in one transaction; duplicates are ignored. Events after a
        missing seq wait in `pending` until it arrives (or is filled). `gap`: (seq, state, blocked
        seconds) recorded with a filled seq. Returns how many were new."""
        async with self.lock:
            if self.purged:
                return 0
            if self._stale:
                await self.load()
            accepted = []
            for seq, event in deliveries:
                next_seq = self.seq + len(accepted) + 1
                if seq < next_seq:
                    known = self.events[seq - 1] if seq <= self.seq else dict(accepted)[seq]
                    if not known.same_content(event) or known.revision != event.revision:
                        log.warning('Match %s seq %s redelivered with different content; kept the first', self.match_id, seq)
                    continue
                if seq > next_seq:
                    if seq not in self.pending:
                        log.warning('Match %s: seq %s after %s; holding it for the missing events',
                                    self.match_id, seq, next_seq - 1)
                    if len(self.pending) < MAX_PENDING:
                        self.pending.setdefault(seq, event)
                    continue
                accepted.append((seq, event))
                while (following := self.seq + len(accepted) + 1) in self.pending:
                    accepted.append((following, self.pending.pop(following)))
            if accepted:
                try:
                    await asyncio.to_thread(self.repository.append, self.match_id, accepted, (),
                                            [gap] if gap and accepted[0][0] == gap[0] else [])
                except BaseException:
                    self._stale = True  # Memory moved ahead of the database; rebuild before reuse.
                    for seq, event in accepted:  # Drained events wait again until the retry.
                        if seq > (gap[0] if gap else 0):
                            self.pending.setdefault(seq, event)
                    raise
                for seq, event in accepted:
                    self._observe(seq, event)
                self.changed.set()
            self.pending = {seq: e for seq, e in self.pending.items() if seq > self.seq}
            # A later gap gets its own timeout: the clock restarts whenever the seq advances.
            self.gap_since = None if not self.pending else (
                time.monotonic() if accepted or self.gap_since is None else self.gap_since)
            return len(accepted)

    def gap(self, now=None):
        """The missing seq blocking delivery, or None."""
        if not self.pending:
            return None
        return {'match_id': self.match_id, 'seq': self.seq + 1, 'pending': len(self.pending), 'state': 'open',
                'age_seconds': round((now or time.monotonic()) - self.gap_since, 1)}

    def placeholder(self, seq):
        """A deleted event that fills a skipped seq: counted by nothing, it keeps seq contiguous."""
        last = self.events[-1] if self.events else None
        return Event(event_id=f'gap-{seq}', match_id=self.match_id, event_type='touch', deleted=True, sequence=seq,
                     period=last.period if last else 1, match_time_seconds=last.match_time_seconds if last else 0,
                     video_seconds=last.video_seconds if last else None)

    async def fill_gap(self, seq, event, state, blocked_seconds):
        """Commit the event for a missing seq (ETL's canonical one, or a placeholder) and record it."""
        if self.seq + 1 != seq:
            return 0  # It arrived meanwhile.
        log.warning('Match %s: seq %s %s after %.0fs', self.match_id, seq, state, blocked_seconds)
        return await self.accept_batch([(seq, event)], gap=(seq, state, blocked_seconds))

    def _observe(self, seq, event):
        self.events.append(event)
        if event.event_type == 'period_end' and not event.deleted:
            self.period_ends.append((seq, event.period))

    def closed_through(self, seq):
        """The last period whose end is observed at seq (0 when none)."""
        return max((period for at, period in self.period_ends if at <= seq), default=0)

    def value_at(self, calculation_id, seq):
        """A calculation's value as of seq, so custom cards cite the same snapshot as ETL stats."""
        history = self.values.get(calculation_id) or [(self.seq, self.engine.get(calculation_id).value)]
        index = bisect.bisect_right(history, seq, key=lambda item: item[0]) - 1
        return history[max(index, 0)][1]

    def calculation(self, result, unattributed=(), seq=None):
        rule = self.engine.rule(result.calculation_id)
        complete = not incomplete_player_rule(rule, unattributed)
        value = result.value if seq is None else self.value_at(result.calculation_id, seq)
        return {'id': result.calculation_id, 'label': self.labels[result.calculation_id],
                'value': value if complete else None, 'version': result.version,
                'available': complete and value is not None, 'complete': complete,
                'unit': rule.unit, 'rule': rule.model_dump(mode='json')}

    def calculations(self, seq=None):
        # Completeness uses the unattributed actions (kept incrementally), not a rescan.
        unattributed = tuple(self._unattributed_actions)
        return {r.calculation_id: self.calculation(r, unattributed, seq) for r in self.engine.calculations}

    async def register(self, rule, label):
        try:
            await self.catch_up()  # Count every action ETL has finalised before registering.
        except Exception as exc:
            raise RuleError('snapshot_unavailable', 'Live match data is temporarily unavailable.', 503) from exc
        async with self.lock:
            self._check_live()
            if rule.match_id != self.match_id:
                raise RuleError('wrong_match', 'Choose a rule for this match', 422)
            if rule.calculation_id not in self.labels and self.engine.count >= self.max_calculations:
                raise RuleError('calculation_capacity', 'This match has reached its custom-stat limit. Existing tracked stats still work.', 409)
            if reason := unsupported_reason(rule, self.reference().get('capabilities')):
                raise RuleError('unavailable_measurement', reason, 422)
            unattributed = tuple(self._unattributed_actions)
            if incomplete_player_rule(rule, unattributed):
                raise RuleError('unavailable_measurement', 'Some matching actions have no player attribution, so this total is unavailable.', 422)
            # Calculate against the actions read so far before publishing into live memory.
            identifier = rule.calculation_id
            if identifier in self.labels:
                result, history = self.engine.get(identifier), None
            else:
                result, history = FilterEngine().register(rule, self.actions), replay(rule, self.actions)
            await asyncio.to_thread(self.repository.register, self.match_id, label,
                                    rule.model_dump(mode='json'), result.model_dump(mode='json'))
            self.engine.register(rule)
            self.labels.setdefault(identifier, label)
            if history is not None:
                self.values[identifier] = history
            self.changed.set()
            return self.calculation(result, unattributed)

    def _check_live(self):
        if self.purged:
            raise RuleError('match_not_found', 'This match is no longer available.', 404)

    def guard(self):
        """Hold while committing a match-scoped write, so a purge cannot interleave."""
        return _Guard(self)

    async def plan(self, planner, prompt, conversation_id=None):
        """A custom-rule plan for the lab. Model work stays outside the match lock."""
        async with self.lock:
            self._check_live()
            if self.info is None:
                raise RuleError('snapshot_unavailable', 'Match details are not available yet.', 503)
            context = {'match_id': self.match_id, 'players': self.info['players'], 'teams': self.info['teams'],
                       'standard_stats': [], 'data_reference': self.reference(),
                       'clock_seconds': self.events[-1].match_time_seconds if self.events else None,
                       'period': self.events[-1].period if self.events else None}
            history = self.conversations.history(conversation_id, self.match_id)
            if sum(len(item['content']) for item in history) + len(prompt) > 6000:
                raise RuleError('conversation_limit', 'Start a new request with the details you have clarified.', 409)
        outcome = await planner.plan(prompt, context, history=history) if history else await planner.plan(prompt, context)
        response = outcome.model_dump(mode='json')
        async with self.lock:
            self._check_live()
            if response.get('status') in {'ready', 'clarification'}:
                response['conversation_id'] = self.conversations.save(
                    conversation_id, self.match_id, history, prompt, assistant_message(response))
        return response

    def event_record(self, seq):
        if not 1 <= seq <= self.seq:
            raise RuleError('event_not_received', 'This event has not been received for this match', 404)
        return {'seq': seq, 'canonical': self.events[seq - 1].model_dump(mode='json')}

    def display(self, seq):
        event = self.events[seq - 1]
        info = self.info or {'teams': [], 'players': []}
        players = {p['id']: p['name'] for p in info['players']}
        teams = {t['id']: t['name'] for t in info['teams']}
        return {'id': event.event_id, 'seq': seq, 'type': event.event_type,
                'player': players.get(event.player_id, event.player_id), 'team': teams.get(event.team_id, event.team_id),
                'minute': event.match_time_seconds // 60, 'match_time_seconds': event.match_time_seconds,
                'period': event.period, 'body_part': event.body_part, 'outcome': event.outcome,
                'revision': event.revision, 'deleted': event.deleted, 'synthetic': self.synthetic}

    async def state(self):
        """Lab view: the latest received events and every custom calculation."""
        try:
            await self.catch_up()
        except Exception:
            log.warning('Match %s: SPADL actions unavailable; showing the last values', self.match_id)
        async with self.lock:
            self._check_live()
            return {'synthetic': self.synthetic, 'match_id': self.match_id, 'fixture': self.fixture, 'seq': self.seq,
                    'events': [self.display(s) for s in range(max(1, self.seq - 99), self.seq + 1)],
                    'calculations': list(self.calculations().values()), 'changed_ids': self.last_changed,
                    'metrics': {'total_rules': self.engine.count, 'shared_inputs': self.engine.leaf_count,
                                'formula_evaluation_count': self.engine.last_formula_evaluation_count,
                                'candidate_count': self.engine.last_candidate_count,
                                'index_probe_count': self.engine.last_index_probe_count,
                                'family_evaluation_count': self.engine.last_family_evaluation_count,
                                'time_probe_count': self.engine.last_time_probe_count,
                                'changed_count': len(self.last_changed)}}


def replay(rule, actions):
    """[(final seq, value)] of a rule over actions in order, so earlier snapshots read earlier values."""
    engine = FilterEngine()
    identifier = engine.register(rule).calculation_id
    history = [(0, engine.get(identifier).value)]
    for action in actions:
        history += [(action.final_seq, r.value) for r in engine.ingest(action) if r.calculation_id == identifier]
    return history


class _Guard:
    def __init__(self, match):
        self.match = match

    async def __aenter__(self):
        await self.match.lock.acquire()
        if self.match.purged:
            self.match.lock.release()
            raise RuleError('match_not_found', 'This match is no longer available.', 404)
        return self.match

    async def __aexit__(self, *exc):
        self.match.lock.release()
