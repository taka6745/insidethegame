"""Cross-match reach: which of the other live matches a viewer's words name, and the small
header that marks content from it. Another match's data is read at that match's own position (its live snapshot),
never at the viewer's seq; access is per request, so no match's own narratives ever mention another."""
import asyncio
import logging

from backend.domain import RuleError
from backend.models.events import minute_label
from backend.services.names import coverage, rarity

log = logging.getLogger(__name__)
TEAM_FIELDS = ('id', 'position', 'name', 'short_name', 'code', 'branding')


def entities(info):
    """Name lists for a match's teams and players."""
    return ([(t['name'], t.get('short_name'), t.get('code'), *(t.get('known_names') or ())) for t in info['teams']]
            + [(p['name'],) for p in info['players']])


def header(match, info):
    """What marks another match's content: its id, fixture and teams (names and branding, never the score)."""
    return {'id': match.match_id, 'fixture': match.fixture,
            'teams': [{k: t.get(k) for k in TEAM_FIELDS} for t in info['teams']]}


class CrossMatch:
    def __init__(self, registry, match_data, config):
        self.registry, self.match_data, self.config = registry, match_data, config

    async def settings(self):
        return await self.config.get('cross-match')

    def others(self, match_id):
        """The other matches this service tracks now (a purge removes a match)."""
        return [m for m in self.registry.matches.values() if m.match_id != match_id and not m.purged]

    async def other(self, match_id, other_id):
        """Another live match by id, or 404 when cross-match reach is off or the match is unknown or cleared."""
        if other_id == match_id or not (await self.settings()).enabled:
            raise RuleError('match_not_found', 'That match is not live here.', 404)
        return self.registry.get(other_id)

    async def named(self, match, text):
        """(other match, its info) when `text` names another live match's team or player more than this match's,
        else None. Words are weighted by rarity across every live match."""
        config = await self.settings()
        others = self.others(match.match_id) if config.enabled else []
        if not others:
            return None
        found = await asyncio.gather(*(self.info_of(m) for m in [match, *others]))
        known = [(m, info) for m, info in zip([match, *others], found) if info]
        weight = rarity([names for _, info in known for names in entities(info)])
        scores = [(max((coverage(text, names, weight) for names in entities(info)), default=0.0), m, info)
                  for m, info in known]
        here = next((s for s, m, _ in scores if m is match), 0.0)
        best = max((row for row in scores if row[1] is not match), key=lambda row: row[0], default=None)
        if best and best[0] >= config.min_name_coverage and best[0] > here:
            return best[1], best[2]
        return None

    async def listing(self, match, snapshot=None):
        """Every live match a viewer of `match` can ask about: its teams, minute played and score (this one's at
        the viewer's snapshot when given), for the question agent and follow planner as context. [] when reach is
        off."""
        if not (await self.settings()).enabled:
            return []
        rows = []
        for m in [match, *self.others(match.match_id)]:
            info = await self.info_of(m)
            if not info:
                continue
            # This match never past the viewer's picture; another where ETL has it (its watermarks), not its newest
            # delivery.
            at = snapshot if m is match else await self.match_data.played(m)
            seconds = at and at.clock_seconds
            rows.append({'match_id': m.match_id, 'this_match': m is match,
                         'teams': [t['name'] for t in info['teams']],
                         'minute': None if seconds is None else minute_label(at.period, seconds),
                         'period': at and at.period, 'score': await self._score(at, info)})
        return rows

    async def _score(self, snapshot, info):
        """Goals per team in `info`'s team order at `snapshot` (ETL's key events), or None when unknown."""
        if snapshot is None:
            return None
        try:
            goals = await self.match_data.score(snapshot, [t['id'] for t in info['teams']])
        except RuleError:
            log.info('Score of %s unavailable for cross-match reach', snapshot.match_id)
            return None
        return [goals.get(t['id'], 0) for t in info['teams']]

    async def info_of(self, match):
        try:
            return await self.match_data.info(match)
        except RuleError:
            log.info('Match info of %s unavailable for cross-match reach', match.match_id)
            return None
