"""End-to-end orchestration with fake agents over the synthetic match itg-syn-0001.

Fixtures: the seeder's match file and the notifications ETL `python -m devtools load-local` wrote for
it (generated data, not a real match). Like local mode, the fixture data already holds the
whole match, so these tests also show the engine never reads ahead of the notifications.
"""
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from narrative_engine.agents.fake import FakeAgents
from narrative_engine.context.compression import EARLIER, Span, tiles
from narrative_engine.core.config import Settings
from narrative_engine.match_data.fixture import FixtureMatchData
from narrative_engine.core.models import (USER_TYPES, KeyEventDetected, MatchClock, MinuteClosed, PresenceChanged)
from narrative_engine.core.orchestrator import EMPTY_MINUTE, MatchOrchestrator
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink, read_notifications

FIXTURES = Path(__file__).parent / "fixtures"
MATCH = "itg-syn-0001-local"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
MESSAGES = [m for _, m in read_notifications(NOTIFICATIONS) if m]
MINUTES = [m.clock for m in MESSAGES if isinstance(m, MinuteClosed)]
KEYS = [m for m in MESSAGES if isinstance(m, KeyEventDetected)]
QUIET = MatchClock(1, 38)  # no events in the synthetic match, so the ETL sends no MinuteClosed for it
PLAYED = sorted(MINUTES + [QUIET])
T0 = datetime(2026, 10, 18, 7, 0, tzinfo=timezone.utc)


class Harness:
    def __init__(self, data=None, store=None, settings=Settings(), author_delay=0.0):
        self.now = T0
        self.loop = asyncio.new_event_loop()  # one loop per engine, as in production
        self.data = data or FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS)
        self.agents = FakeAgents(author_delay)
        self.store = store or MemoryStore()
        self.sink = MemorySink(self.store)
        self.engine = MatchOrchestrator(MATCH, self.data, self.agents, self.store, self.sink, settings,
                                        now=lambda: self.now)

    def run(self, messages):
        async def go():
            for m in messages:
                await self.engine.handle(m)
        self.loop.run_until_complete(go())
        return self

    def wait(self, coroutine):
        return self.loop.run_until_complete(coroutine)

    def calls(self, agent):
        return [v for a, v in self.agents.calls if a == agent]

    def narratives(self, user_type=None):
        return self.wait(self.store.narratives(MATCH, user_type))

    def active_blocks(self):
        return self.wait(self.store.active_blocks(MATCH))

    def spans(self):
        return [Span(b.level, b.coversFrom, b.coversTo) for b in self.active_blocks()]

    def steps(self, user_type="neutral:casual"):
        return [n.stepId.split(":", 1)[1] for n in self.narratives(user_type)]


def presence(counts, seconds):
    return PresenceChanged(MATCH, counts, T0 + timedelta(seconds=seconds))


def test_full_match_with_all_buckets():
    h = Harness().run(MESSAGES)
    blocks = h.active_blocks()
    assert [(b.level, b.coversFrom, b.coversTo) for b in blocks] == [
        (EARLIER, MatchClock(1, 0), MatchClock(1, 47)), (EARLIER, MatchClock(2, 45), MatchClock(2, 95))]
    assert len(h.calls("summarise")) == len(MINUTES) == 98
    assert h.store.blocks[f"block:{MATCH}:0:{QUIET.key}:{QUIET.key}"].summary == EMPTY_MINUTE
    assert h.engine.cp["status"] == "complete"

    steps = h.steps()
    kinds = Counter(s.split(":")[0] for s in steps)
    assert kinds["key"] == len(KEYS) == 9 and kinds["halfTime"] == 1 and kinds["fullTime"] == 1
    assert kinds["scheduled"] >= 1 and steps[-1] == "fullTime:2"
    for user_type in USER_TYPES:
        assert h.steps(user_type) == steps
        assert [n.seq for n in h.narratives(user_type)] == list(range(1, len(steps) + 1))
    assert len(h.sink.published) == 12 * len(steps)


def test_no_long_gap_without_a_narrative_step():
    h = Harness().run(MESSAGES)
    index = {c: i for i, c in enumerate(PLAYED)}
    clocks = sorted(index[n.matchTime] for n in h.narratives("home:simple"))
    gaps = [b - a for a, b in zip([0] + clocks, clocks)]
    assert max(gaps) <= Settings().fallback_minutes + 1


def test_goal_then_var_overturn_gives_two_steps_and_the_second_knows():
    h = Harness().run(MESSAGES)
    goal, var = [k for k in KEYS if k.keyType in ("Goal", "VarOverturn") and k.clock.periodId == 2][:2]
    assert var.keyType == "VarOverturn"
    by_reason = {v["trigger_reason"]: v for v in h.calls("author") if v["user_type"] == "away:experienced"}
    goal_call = next(v for r, v in by_reason.items() if "Goal for Harbour Athletic" in r and "53'" in r)
    var_call = next(v for r, v in by_reason.items() if "VAR overturns" in r)
    assert "overturned" not in goal_call["key_event_ledger"]
    assert "Goal for Harbour Athletic, Adeyemi [later overturned by VAR]" in var_call["key_event_ledger"]
    assert goal_call["trigger_reason"].splitlines()[0] in var_call["narrative_excerpts"]


def test_author_never_reads_past_the_announced_horizon():
    stats = {MatchClock(1, 22): [{"position": p, "periodId": 1, "minuteLabel": "23'", "goals": 0, "possessionPct": 50,
                                  "shots": 1, "shotsOnTarget": 0, "passes": 10, "passesCompleted": 9, "corners": 0,
                                  "fouls": 0, "yellowCards": 0, "redCards": 0} for p in ("home", "away")]}
    stats[MatchClock(1, 23)] = [{**r, "minuteLabel": "24'", "goals": 1} for r in stats[MatchClock(1, 22)]]
    data = FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS, stats=stats)
    first_goal = KEYS[0]
    h = Harness(data).run(MESSAGES[:MESSAGES.index(first_goal) + 1])
    call = next(v for v in h.calls("author") if v["trigger_reason"].startswith("Key event"))
    assert call["key_event_ledger"].count("\n- ") == 0 and "Goal for Riverside FC, Mensah" in call["key_event_ledger"]
    assert "As of 23'" in call["game_state_statistics"]  # minute 24' is not closed yet
    times = [line.split()[0] for line in call["match_events"].splitlines() if line.startswith("  ") and line.strip()[:1].isdigit()]
    assert times and max(times) == "23:09" and "GOAL" in call["match_events"]


def test_duplicate_messages_change_nothing():
    once = Harness().run(MESSAGES)
    twice = Harness().run([m for m in MESSAGES for _ in (0, 1)])
    assert twice.steps() == once.steps()
    assert len(twice.agents.calls) == len(once.agents.calls)
    assert len(twice.sink.published) == len(once.sink.published)


def test_missing_and_out_of_order_minutes_are_caught_up():
    shuffled = [m for i, m in enumerate(MESSAGES) if not (isinstance(m, MinuteClosed) and i % 3 == 0)]
    for i in range(0, len(shuffled) - 1, 7):
        shuffled[i], shuffled[i + 1] = shuffled[i + 1], shuffled[i]
    h = Harness().run(shuffled)
    assert len(h.calls("summarise")) == 98
    assert tiles(h.spans(), PLAYED)
    assert h.engine.cp["status"] == "complete"


def test_quiet_minute_gets_a_fixed_block_without_a_model_call():
    data = FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS)
    quiet = MatchClock(1, 10)
    data.raw = [e for e in data.raw if (e["periodId"], e["timeMin"]) != (1, 10)]
    h = Harness(data).run([m for m in MESSAGES if not (isinstance(m, MinuteClosed) and m.clock == quiet)])
    block = h.store.blocks[f"block:{MATCH}:0:{quiet.key}:{quiet.key}"]
    assert block.summary == EMPTY_MINUTE and block.promptVersion == "fixed-empty" and block.model is None
    assert len(h.calls("summarise")) == 97
    assert tiles(h.spans(), PLAYED)


def test_author_runs_are_serialised_per_bucket_and_capped():
    h = Harness(settings=Settings(author_concurrency=3), author_delay=0.01)
    before = MESSAGES[:MESSAGES.index(KEYS[1])]
    h.run([m for m in before if not isinstance(m, KeyEventDetected)])

    async def two_at_once():
        await asyncio.gather(h.engine.handle(KEYS[0]), h.engine.handle(KEYS[1]))
    h.wait(two_at_once())
    assert h.agents.max_running <= 3
    for user_type in USER_TYPES:
        first, second = [n for n in h.narratives(user_type) if n.trigger.type == "keyEvent"]
        assert first.stepId.endswith(f"key:{KEYS[0].id}") and second.seq == first.seq + 1
        assert first.text in next(v["narrative_excerpts"] for v in h.calls("author")
                                  if v["user_type"] == user_type and "Penalty to" in v["trigger_reason"])


def test_presence_limits_buckets_and_falls_back_when_stale():
    h = Harness()
    h.run([presence({"home:casual": 1, "away:analyst": 2, "neutral:simple": 0}, 0)])
    h.run(MESSAGES[:MESSAGES.index(KEYS[0]) + 1])
    assert {n.userType for n in h.narratives()} == {"away:analyst", "home:casual"}
    assert sorted(n.userType for n in h.narratives() if n.trigger.type == "keyEvent") == ["away:analyst", "home:casual"]

    h.now = T0 + timedelta(seconds=Settings().presence_stale_seconds + 1)
    h.run(MESSAGES[MESSAGES.index(KEYS[0]) + 1:MESSAGES.index(KEYS[1]) + 1])
    assert {n.userType for n in h.narratives() if n.stepId.endswith(f"key:{KEYS[1].id}")} == set(USER_TYPES)


def test_presence_ignores_older_messages_and_catches_up_new_buckets():
    h = Harness()
    h.run([presence({"home:casual": 1}, 10), presence({"home:casual": 1, "away:simple": 1}, 5)])
    assert h.engine.active_buckets() == ["home:casual"]
    h.run(MESSAGES[:30])
    h.run([presence({"home:casual": 1, "away:simple": 1}, 20)])
    catch_up = [n for n in h.narratives() if n.trigger.type == "catchUp"]
    assert [n.userType for n in catch_up] == ["away:simple"]
    assert "just joined" in h.calls("author")[-1]["trigger_reason"]


def test_restart_resumes_from_the_checkpoint():
    store = MemoryStore()
    half = MESSAGES.index(KEYS[4])
    first = Harness(store=store).run(MESSAGES[:half])
    second = Harness(store=store).run(MESSAGES[half - 5:])  # some redelivered
    single = Harness().run(MESSAGES)
    assert len(first.calls("summarise")) + len(second.calls("summarise")) == 98
    assert second.steps() == single.steps()
    assert [n.seq for n in second.narratives("home:analyst")] == list(range(1, len(single.steps()) + 1))


def test_a_failed_author_call_spares_other_buckets_and_redelivery_retries_it():
    h = Harness(author_delay=0.01)  # other buckets are still running when one fails
    first_goal = MESSAGES.index(KEYS[0])
    h.run(MESSAGES[:first_goal])
    failing, real_author, failures = USER_TYPES[0], h.agents.author, []  # first in, others still queued

    async def flaky(variables):
        if variables["user_type"] == failing and not failures:
            failures.append(1)
            raise RuntimeError("model unavailable")
        return await real_author(variables)
    h.agents.author = flaky
    try:
        h.run([KEYS[0]])
    except RuntimeError:
        pass
    step = f"{MATCH}:key:{KEYS[0].id}"
    done = {n.userType for n in h.store.items.values() if n.stepId == step}  # without running the loop again
    assert failures and done == set(USER_TYPES) - {failing}
    before = len(h.calls("author"))
    h.run([KEYS[0]])  # Service Bus redelivers the uncompleted message
    assert h.narratives(failing)[-1].stepId == step and len(h.calls("author")) == before + 1


def test_accept_records_at_once_and_the_worker_catches_up_like_handle():
    reference = Harness().run(MESSAGES)
    h = Harness(author_delay=0.001)

    async def go():
        for m in MESSAGES:
            await h.engine.accept(m)  # never waits for model calls
        recorded = len(h.agents.calls)
        while h.engine.worker and not h.engine.worker.done():
            await h.engine.worker
        return recorded
    recorded = h.wait(go())
    assert recorded < len(reference.agents.calls)  # the backlog was left to the worker
    assert h.engine.cp["closedThrough"] == MINUTES[-1].key and h.engine.cp["pending"] == []
    assert h.steps() == reference.steps() and h.engine.cp["status"] == "complete"
    for user_type in USER_TYPES:
        assert [n.seq for n in h.narratives(user_type)] == list(range(1, len(reference.steps()) + 1))


def test_restart_mid_backlog_resumes_from_the_checkpoint_without_gaps_or_repeats():
    store = MemoryStore()
    first = Harness(store=store, author_delay=0.001)

    async def record_all_then_crash():
        for m in MESSAGES:
            await first.engine.record(m)
        first.engine.kick()
        while len(first.sink.published) < 30:  # part-way through the backlog
            await asyncio.sleep(0)
        first.engine.worker.cancel()
    first.wait(record_all_then_crash())
    assert first.engine.cp["closedThrough"] == MINUTES[-1].key  # every message was recorded before the crash

    second = Harness(store=store)  # a new process on the same Cosmos state; no messages are redelivered
    second.wait(second.engine.work())
    reference = Harness().run(MESSAGES)
    assert second.steps() == reference.steps()
    for user_type in USER_TYPES:
        assert [n.seq for n in second.narratives(user_type)] == list(range(1, len(reference.steps()) + 1))
    assert len({n.id for n in second.narratives()}) == len(second.narratives()) == 12 * len(reference.steps())


def test_the_worker_retries_failed_work():
    h = Harness()
    h.engine.retry_backoff = 0.001
    real, failures = h.agents.summarise, []

    async def flaky(variables):
        if len(failures) < 2:
            failures.append(1)
            raise RuntimeError("LLM unavailable")
        return await real(variables)
    h.agents.summarise = flaky

    async def go():
        for m in MESSAGES[:30]:
            await h.engine.accept(m)
        while h.engine.worker and not h.engine.worker.done():
            await h.engine.worker
    h.wait(go())
    closed = [m for m in MESSAGES[:30] if isinstance(m, MinuteClosed)][-1]
    assert len(failures) == 2 and h.engine.cp["lastSummarised"] == closed.clock.key


def test_a_failed_publish_is_sent_on_retry_not_lost():
    """Stored before publishing, so a retry finds the narrative stored and must still send it."""
    h = Harness()
    h.engine.retry_backoff = 0.001
    real, failures = h.sink.publish, []

    async def flaky(narrative):
        if not failures:
            failures.append(narrative.id)
            raise RuntimeError("Service Bus link not ready")
        await real(narrative)
    h.sink.publish = flaky

    async def go():
        for m in MESSAGES:
            await h.engine.accept(m)
        while h.engine.worker and not h.engine.worker.done():
            await h.engine.worker
    h.wait(go())
    stored = {n.id for n in h.narratives()}
    assert failures and failures[0] in stored
    assert {n.id for n in h.sink.published} == stored


def test_report_shows_every_block_and_step():
    from narrative_engine.devtools.report import render
    h = Harness().run(MESSAGES)
    blocks, narratives = list(h.store.blocks.values()), h.narratives()
    page = render(MATCH, blocks, narratives)
    assert page.count('class="card minute') == len(MINUTES) + 1  # plus the quiet minute's fixed block
    assert page.count('class="card compress') == len(blocks) - len(MINUTES) - 1
    assert page.count('class="card narrative') == len({n.stepId for n in narratives})
    assert page.count('class="bucket"') == len(narratives) and "<script>" in page
