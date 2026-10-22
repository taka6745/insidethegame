"""SPADL sync against a rebuild that overtakes it (live: a failed event write rebuilt the match while a read was in
flight, the read then marked actions counted that the rebuild had dropped, and every later read was "out of order")."""
import asyncio

from backend.services.live_match import LiveMatch


def row(action_id, final_seq):
    return {'actionId': action_id, 'periodId': 1, 'clockSeconds': action_id, 'teamId': 'home', 'typeName': 'pass',
            'resultName': 'success', 'bodypartName': 'foot', 'startX': 50.0, 'startY': 34.0, 'endX': 60.0,
            'endY': 34.0, 'startZone': 'middle_third', 'endZone': 'middle_third', 'seq': final_seq,
            'finalSeq': final_seq}


ROWS = [row(0, 1), row(1, 2), row(2, 3), row(3, 9)]  # Nothing becomes final in (3, 6].


class Repository:
    def load(self, match_id):
        return [], []


class Dab:
    """Serves ROWS by finalSeq; the first read waits until the test has rebuilt the match."""

    def __init__(self):
        self.reading, self.release, self.reads = asyncio.Event(), asyncio.Event(), []

    async def spadl_actions(self, match_id, after, seq):
        self.reads.append((after, seq))
        if len(self.reads) == 1:
            self.reading.set()
            await self.release.wait()
        return [r for r in ROWS if after < r['finalSeq'] <= seq]


def test_a_read_overtaken_by_a_rebuild_is_read_again_from_the_rebuilt_position():
    async def go():
        match = LiveMatch({'match_id': 'm', 'fixture': 'f'}, Repository())
        match.info = {'teams': [{'id': 'home', 'position': 'home'}]}
        dab = Dab()
        await match.sync_actions(_Plain(), 3)  # Hold actions 0..2 (finalSeq <= 3).
        assert [a.action_id for a in match.actions] == [0, 1, 2]
        task = asyncio.create_task(match.sync_actions(dab, 6))
        await dab.reading.wait()
        await match.load()  # The rebuild accept_batch runs after a failed write: held actions start again at 0.
        dab.release.set()
        await task
        # Not "6 counted, nothing held": that state made every later read start at action 3 with 0 held.
        assert [a.action_id for a in match.actions] == [0, 1, 2] and match.actions_seq == 6
        await match.sync_actions(_Plain(), 9)
        assert [a.action_id for a in match.actions] == [0, 1, 2, 3]
        assert dab.reads == [(3, 6), (0, 6)]
    asyncio.run(go())


class _Plain(Dab):
    def __init__(self):
        super().__init__()
        self.reads = [None]  # Never waits.
