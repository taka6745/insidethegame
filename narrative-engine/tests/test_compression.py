from narrative_engine.context.compression import (EARLIER, FIVE_MINUTE, MINUTE, Span, apply, close_period, compress_all, minute,
                                          tiles)
from narrative_engine.core.models import MatchClock

# The design doc counts minutes from 1; the Opta clock counts from 0, so doc minute n is timeMin n - 1.
FIRST_HALF = [MatchClock(1, m) for m in range(0, 47)]    # 1' .. 45+2'
SECOND_HALF = [MatchClock(2, m) for m in range(45, 95)]  # 46' .. 90+5'


def doc(level, first, last):
    return Span(level, MatchClock(1, first - 1), MatchClock(1, last - 1))


def doc_minutes(first, last):
    return [doc(MINUTE, m, m) for m in range(first, last + 1)]


# README.md, Context compression: non-superseded blocks after each listed minute.
WORKED_EXAMPLE = {
    11: [doc(FIVE_MINUTE, 1, 5)] + doc_minutes(6, 11),
    16: [doc(FIVE_MINUTE, 1, 5), doc(FIVE_MINUTE, 6, 10)] + doc_minutes(11, 16),
    21: [doc(FIVE_MINUTE, 1, 5), doc(FIVE_MINUTE, 6, 10), doc(FIVE_MINUTE, 11, 15)] + doc_minutes(16, 21),
    26: [doc(EARLIER, 1, 10), doc(FIVE_MINUTE, 11, 15), doc(FIVE_MINUTE, 16, 20)] + doc_minutes(21, 26),
    31: [doc(EARLIER, 1, 10), doc(FIVE_MINUTE, 11, 15), doc(FIVE_MINUTE, 16, 20), doc(FIVE_MINUTE, 21, 25)]
        + doc_minutes(26, 31),
    36: [doc(EARLIER, 1, 20), doc(FIVE_MINUTE, 21, 25), doc(FIVE_MINUTE, 26, 30)] + doc_minutes(31, 36),
    41: [doc(EARLIER, 1, 20), doc(FIVE_MINUTE, 21, 25), doc(FIVE_MINUTE, 26, 30), doc(FIVE_MINUTE, 31, 35)]
        + doc_minutes(36, 41),
    46: [doc(EARLIER, 1, 30), doc(FIVE_MINUTE, 31, 35), doc(FIVE_MINUTE, 36, 40)] + doc_minutes(41, 46),
}


def replay(clocks):
    """Yield (played minutes, active spans, compressions) after each closed minute.

    The last minute of each period closes that period, as the orchestrator does.
    """
    period_ends = {c.periodId: c for c in clocks}
    active, played = [], []
    for clock in clocks:
        played.append(clock)
        active, done = compress_all(active + [minute(clock)])
        if period_ends[clock.periodId] == clock and (c := close_period(active, clock.periodId)):
            active = apply(active, c)
            done.append(c)
        yield list(played), active, done


def test_first_half_matches_worked_example():
    for played, active, _ in replay(FIRST_HALF):
        expected = WORKED_EXAMPLE.get(len(played))
        if expected:
            assert active == expected, f"after doc minute {len(played)}"
    assert set(WORKED_EXAMPLE) <= set(range(1, len(FIRST_HALF) + 1))


def test_45_plus_1_is_labelled_like_the_broadcast():
    assert doc_minutes(46, 46)[0].start.label == "45+1'"


def test_whole_match_stays_tiled_and_bounded():
    for played, active, done in replay(FIRST_HALF + SECOND_HALF):
        assert tiles(active, played), played[-1]
        period = played[-1].periodId
        current = [s.level for s in active if s.periodId == period]
        assert all(s.level == EARLIER for s in active if s.periodId < period)
        assert current.count(EARLIER) <= 1
        assert current.count(FIVE_MINUTE) <= 3
        assert current.count(MINUTE) <= 10
        for c in done:
            assert c.output.start == c.inputs[0].start and c.output.end == c.inputs[-1].end


def test_no_block_spans_half_time():
    outputs = [c.output for *_, done in replay(FIRST_HALF + SECOND_HALF) for c in done]
    assert all(s.start.periodId == s.end.periodId for s in outputs)
    # P1 timeMin 45 and P2 timeMin 45 are different minutes; ordering by period keeps them apart.
    assert MatchClock(1, 46) < MatchClock(2, 45)


def test_each_finished_half_collapses_to_one_block():
    *_, (played, active, _) = replay(FIRST_HALF + SECOND_HALF)
    assert active == [Span(EARLIER, FIRST_HALF[0], FIRST_HALF[-1]), Span(EARLIER, SECOND_HALF[0], SECOND_HALF[-1])]
    second_half_start = list(replay(FIRST_HALF + SECOND_HALF))[len(FIRST_HALF) + 10][1]
    assert second_half_start[0] == Span(EARLIER, FIRST_HALF[0], FIRST_HALF[-1])
    assert [s.level for s in second_half_start[1:]] == [FIVE_MINUTE] + [MINUTE] * 6
    assert close_period(active, 1) is None


def test_tiles_detects_gaps_and_overlaps():
    played = [MatchClock(1, m) for m in range(4)]
    assert tiles([Span(MINUTE, played[0], played[1]), Span(MINUTE, played[2], played[3])], played)
    assert not tiles([Span(MINUTE, played[0], played[1]), Span(MINUTE, played[3], played[3])], played)
    assert not tiles([Span(MINUTE, played[0], played[2]), Span(MINUTE, played[2], played[3])], played)
    assert not tiles([Span(MINUTE, played[0], played[2])], played)


def test_a_step_reads_only_blocks_complete_by_its_horizon():
    """A key event recorded after later minutes were summarised (messages out of order) reads the superseded
    blocks up to its horizon, never the merge that covers later minutes."""
    import asyncio
    from narrative_engine.context.builder import ContextBuilder
    from narrative_engine.core.models import ContextBlock
    from narrative_engine.store.memory import MemoryStore

    def block(start, end, level):
        return ContextBlock(f"b{start}-{end}", "m", level, MatchClock(1, start), MatchClock(1, end), "s",
                            MatchClock(1, end), None, None, None, "t")

    async def go():
        store = MemoryStore()
        for m in range(5):
            await store.put_block(block(m, m, MINUTE))
        await store.supersede(block(0, 4, FIVE_MINUTE), [f"b{m}-{m}" for m in range(5)])
        await store.put_block(block(5, 5, MINUTE))
        builder = ContextBuilder(None, store)
        spans = lambda blocks: [(b.coversFrom.timeMin, b.coversTo.timeMin) for b in blocks]
        assert spans(await builder.blocks("m", MatchClock(1, 5), 59)) == [(0, 4), (5, 5)]  # the active blocks
        assert spans(await builder.blocks("m", MatchClock(1, 5), 20)) == [(0, 4)]  # minute 5 is not over at 5:20
        assert spans(await builder.blocks("m", MatchClock(1, 3), 20)) == [(0, 0), (1, 1), (2, 2)]
    asyncio.run(go())
