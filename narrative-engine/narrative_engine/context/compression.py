"""Decaying-resolution context rules (docs/design/narrative-generation-engine.md §5.3). Pure, no I/O.

Levels: 0 = one-minute summary, 1 = five-minute block, 2 = earlier block.
1. At 11 minute summaries, compress the oldest 5 into a five-minute block.
2. At 4 five-minute blocks, merge the oldest 2 and any earlier block into one earlier block.
Blocks never span periods: both rules count only the current period's spans, and when a
period ends `close_period` merges all of its spans into one earlier block for that period.
"""
from dataclasses import dataclass

from narrative_engine.core.models import MatchClock

MINUTE, FIVE_MINUTE, EARLIER = 0, 1, 2
TIERS = {MINUTE: "minute", FIVE_MINUTE: "five-minute", EARLIER: "twenty-minute"}
HALF = "half"  # a closed period's single block
MINUTES_BEFORE_COMPRESS, MINUTES_PER_BLOCK = 11, 5
BLOCKS_BEFORE_MERGE, BLOCKS_PER_MERGE = 4, 2


@dataclass(frozen=True)
class Span:
    level: int
    start: MatchClock
    end: MatchClock

    @property
    def key(self):
        return f"{self.level}:{self.start.key}:{self.end.key}"

    @property
    def periodId(self):
        return self.start.periodId


@dataclass(frozen=True)
class Compression:
    inputs: tuple
    output: Span


def minute(clock):
    return Span(MINUTE, clock, clock)


def _merge(level, inputs):
    inputs = tuple(sorted(inputs, key=lambda s: s.start))
    return Compression(inputs, Span(level, inputs[0].start, inputs[-1].end))


def next_compression(active):
    """The next compression due in the current (latest) period, or None."""
    if not active:
        return None
    period = max(s.periodId for s in active)
    current = sorted((s for s in active if s.periodId == period), key=lambda s: s.start)
    by_level = {level: [s for s in current if s.level == level] for level in (MINUTE, FIVE_MINUTE, EARLIER)}
    if len(by_level[MINUTE]) >= MINUTES_BEFORE_COMPRESS:
        return _merge(FIVE_MINUTE, by_level[MINUTE][:MINUTES_PER_BLOCK])
    if len(by_level[FIVE_MINUTE]) >= BLOCKS_BEFORE_MERGE:
        return _merge(EARLIER, by_level[EARLIER] + by_level[FIVE_MINUTE][:BLOCKS_PER_MERGE])
    return None


def close_period(active, period_id):
    """Merge every span of a finished period into one earlier block, or None if already one."""
    spans = [s for s in active if s.periodId == period_id]
    if not spans or (len(spans) == 1 and spans[0].level == EARLIER):
        return None
    return _merge(EARLIER, spans)


def apply(active, compression):
    remaining = [s for s in active if s not in compression.inputs]
    return sorted(remaining + [compression.output], key=lambda s: s.start)


def compress_all(active):
    """Apply every due compression in order. Returns (active spans, compressions run)."""
    active, done = sorted(active, key=lambda s: s.start), []
    while (c := next_compression(active)) is not None:
        active = apply(active, c)
        done.append(c)
    return active, done


def tiles(active, played):
    """True if the spans cover exactly the played minutes, in order, with no gaps or overlaps."""
    played = sorted(played)
    position = 0
    for span in sorted(active, key=lambda s: s.start):
        if position >= len(played) or played[position] != span.start:
            return False
        while position < len(played) and played[position] <= span.end:
            position += 1
        if played[position - 1] != span.end:
            return False
    return position == len(played)
