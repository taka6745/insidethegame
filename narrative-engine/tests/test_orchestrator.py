"""End-to-end orchestration with fake agents over the synthetic match itg-syn-0001.

Fixtures: the seeder's match file and the notifications ETL `python -m devtools load-local` wrote for
it (generated data, not a real match). Like local mode, the fixture data already holds the
whole match, so these tests also show the engine never reads ahead of the notifications.
"""
import asyncio
import json
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY

from doubles.fake_agents import FakeAgents
from narrative_engine.context.compression import EARLIER, Span, tiles
from narrative_engine.core.config import Settings
from doubles.fixture_data import FixtureMatchData
from narrative_engine.audience.targets import Targets
from doubles.targets import DEFAULT_BUCKETS as USER_TYPES, StaticTargets, default_targets
from narrative_engine.core.models import KeyEventDetected, MatchClock, MinuteClosed, PeriodChanged
from narrative_engine.core.orchestrator import EMPTY_MINUTE, EMPTY_SPAN, MatchOrchestrator, stoppage
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink, read_notifications

FIXTURES = Path(__file__).parent / "fixtures"
MATCH = "itg-syn-0001-local"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
ACTIONS = FIXTURES / "itg-syn-0001-spadl.json"
MESSAGES = [m for _, m in read_notifications(NOTIFICATIONS) if m]
MINUTES = [m.clock for m in MESSAGES if isinstance(m, MinuteClosed)]
KEYS = [m for m in MESSAGES if isinstance(m, KeyEventDetected)]
QUIET = MatchClock(1, 38)  # no events in the synthetic match, so the ETL sends no MinuteClosed for it
PLAYED = sorted(MINUTES + [QUIET])
T0 = datetime(2026, 10, 18, 7, 0, tzinfo=timezone.utc)


class Harness:
    def __init__(self, data=None, store=None, settings=Settings(), author_delay=0.0, targets=None, prompts=None):
        self.now = T0
        self.loop = asyncio.new_event_loop()  # one loop per engine, as in production
        self.data = data or FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS, actions_path=ACTIONS)
        self.agents = FakeAgents(author_delay)
        self.store = store or MemoryStore()
        self.sink = MemorySink(self.store)
        self.engine = MatchOrchestrator(MATCH, self.data, self.agents, self.store, self.sink, settings,
                                        now=lambda: self.now, targets=targets or StaticTargets(default_targets()),
                                        prompts=prompts)

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


class MutableTargets:
    """The user backend's audience-config, changed by the test between messages."""
    def __init__(self, *bucket_ids):
        self.revision, self.asked = 0, []
        self.set(*bucket_ids)

    def set(self, *bucket_ids):
        self.revision += 1
        self.items = tuple(t for t in default_targets() if t["bucket_id"] in bucket_ids)

    async def current(self, match_id):
        self.asked.append(match_id)
        return Targets(self.revision, self.items)


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
    by_reason = {v["trigger_reason"]: v for v in h.calls("author") if v["bucket_id"] == "away:experienced"}
    goal_call = next(v for r, v in by_reason.items() if "Goal for Harbour Athletic" in r and "53'" in r)
    var_call = next(v for r, v in by_reason.items() if "VAR overturns" in r)
    assert "overturned" not in goal_call["key_event_ledger"]
    assert "Goal for Harbour Athletic, Adeyemi [later overturned by VAR]" in var_call["key_event_ledger"]
    assert goal_call["trigger_reason"].splitlines()[0] in var_call["narrative_excerpts"]


def test_author_never_reads_past_the_announced_horizon():
    def rows(goals):
        return [{"statId": f"{t}:{k}", "kind": k, "contestantId": t, "value": v, "available": True, "unit": u}
                for t in ("c-riv", "c-har") for k, v, u in (("possession", 50.0, "%"), ("shots", goals, ""))]
    data = FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS, stats=None, actions_path=ACTIONS)
    first_goal = KEYS[0]
    goal_seq = next(e["seq"] for e in data.raw if e["typeId"] == 16)
    data.stats = {1: rows(0), goal_seq: rows(1)}  # catalogue rows by seq; the goal's minute is not summarised yet
    h = Harness(data).run(MESSAGES[:MESSAGES.index(first_goal) + 1])
    call = next(v for v in h.calls("author") if v["trigger_reason"].startswith("Key event"))
    assert call["key_event_ledger"].count("\n- ") == 0 and "Goal for Riverside FC, Mensah" in call["key_event_ledger"]
    assert "As of 23'" in call["game_state_statistics"] and "| Shots (on target) | 0 (n/a) | 0 (n/a) |" in \
        call["game_state_statistics"] and "0 - 0" in call["game_state_statistics"]  # minute 24' is not closed yet
    times = [line.split()[0] for line in call["match_events"].splitlines() if line.startswith("  ") and line.strip()[:1].isdigit()]
    assert times and max(times) == "23:09" and "shot, success" in call["match_events"]
    assert "key event: Goal for Riverside FC, Mensah" in call["match_events"]


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


def test_a_merge_of_only_quiet_minutes_needs_no_model_call():
    data = FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS)
    data.raw = [e for e in data.raw if (e["periodId"], e["timeMin"]) >= (1, 11)]
    h = Harness(data, targets=StaticTargets([])).run([MinuteClosed(MATCH, MatchClock(1, 10), T0)])
    assert h.agents.calls == []
    first = h.active_blocks()[0]
    assert (first.level, first.coversFrom, first.coversTo) == (1, MatchClock(1, 0), MatchClock(1, 4))
    assert first.summary == EMPTY_SPAN and first.promptVersion == "fixed-empty"


def test_a_periods_last_minute_is_merged_once_and_stoppage_time_has_no_scheduled_step():
    h = Harness()
    at, compress = [], h.engine._compress

    async def watched():
        at.append(h.engine.cp["lastSummarised"])
        await compress()
    h.engine._compress = watched
    h.run(MESSAGES)
    ends = set(h.engine.cp["periodEnds"].values())
    assert at and not ends & set(at)  # `_close_periods` merges the period's last minute
    scheduled = [MatchClock.parse(s.split(":")[1]) for s in h.steps() if s.startswith("scheduled:")]
    assert scheduled and not [c for c in scheduled if stoppage(c)]
    assert h.engine.cp["status"] == "complete"


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
                                  if v["bucket_id"] == user_type and "Penalty to" in v["trigger_reason"])


def test_the_first_bucket_of_a_step_is_written_alone_to_warm_the_prompt_cache():
    h = Harness(settings=Settings(author_concurrency=4), author_delay=0.01)
    h.run([m for m in MESSAGES[:MESSAGES.index(KEYS[0])] if not isinstance(m, KeyEventDetected)])
    real_author, started, done = h.agents.author, [], []

    async def recording(variables, prompt=None, feedback=None):
        started.append((variables["bucket_id"], list(done)))
        result = await real_author(variables, prompt)
        done.append(variables["bucket_id"])
        return result
    h.agents.author = recording
    h.run([KEYS[0]])
    assert [b for b, _ in started] == list(USER_TYPES)
    assert started[0][1] == [] and all(before[0] == USER_TYPES[0] for _, before in started[1:])  # siblings wait for it
    assert h.agents.max_running == 4  # then run together, within the cap


def test_targets_limit_buckets_and_none_writes_nothing():
    targets = MutableTargets("home:casual", "away:analyst")
    h = Harness(targets=targets).run(MESSAGES[:MESSAGES.index(KEYS[0]) + 1])
    assert {n.userType for n in h.narratives()} == {"away:analyst", "home:casual"}
    assert set(targets.asked) == {MATCH}  # the run-scoped matchId; the backend resolves its fixture
    assert {n.audienceRevision for n in h.narratives()} == {1}

    targets.set()
    h.run(MESSAGES[MESSAGES.index(KEYS[0]) + 1:MESSAGES.index(KEYS[1]) + 1])
    assert not [n for n in h.narratives() if n.stepId.endswith(f"key:{KEYS[1].id}")]
    assert h.engine.cp["status"] == "live" and h.engine.cp["pending"] == []


def test_a_newly_active_bucket_gets_a_catch_up_from_the_poll():
    targets = MutableTargets("home:casual")
    h = Harness(targets=targets).run(MESSAGES[:30])
    targets.set("home:casual", "away:simple")
    h.wait(h.engine.sync_targets())
    h.wait(h.engine.worker)
    catch_up = [n for n in h.narratives() if n.trigger.type == "catchUp"]
    assert [(n.userType, n.audienceRevision) for n in catch_up] == [("away:simple", 2)]
    author = h.calls("author")[-1]
    assert "just been enabled" in author["trigger_reason"] and author["bucket_id"] == "away:simple"
    assert "Team support. Supports the away team." in author["user_type"]  # layer + option descriptions
    assert "This audience supports Harbour Athletic." in author["user_type"]
    h.wait(h.engine.sync_targets())  # unchanged revision: nothing new
    assert len([n for n in h.narratives() if n.trigger.type == "catchUp"]) == 1


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

    async def flaky(variables, prompt=None):
        if variables["bucket_id"] == failing and not failures:
            failures.append(1)
            raise RuntimeError("model unavailable")
        return await real_author(variables, prompt)
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
    h = Harness(settings=Settings(retry_seconds=0.001))
    real, failures = h.agents.summarise, []

    async def flaky(variables, prompt=None):
        if len(failures) < 2:
            failures.append(1)
            raise RuntimeError("LLM unavailable")
        return await real(variables, prompt)
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
    h = Harness(settings=Settings(retry_seconds=0.001))
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
    from devtools.report import render
    h = Harness().run(MESSAGES)
    blocks, narratives = list(h.store.blocks.values()), h.narratives()
    page = render(MATCH, blocks, narratives)
    assert page.count('class="card minute') == len(MINUTES) + 1  # plus the quiet minute's fixed block
    assert page.count('class="card compress') == len(blocks) - len(MINUTES) - 1
    assert page.count('class="card narrative') == len({n.stepId for n in narratives})
    assert page.count('class="bucket"') == len(narratives) and "<script>" in page


def test_period_end_steps_run_on_period_ended_at_the_end_events_clock():
    """No waiting for the end minute's MinuteClosed (or the ETL's idle flush): the step's data reaches the
    End event's second, not :59."""
    ends = {m.periodId: i for i, m in enumerate(MESSAGES) if isinstance(m, PeriodChanged) and not m.started}
    early = [m for i, m in enumerate(MESSAGES)
             if not (isinstance(m, MinuteClosed) and any(i > at and m.clock.periodId == p for p, at in ends.items()))]
    h = Harness().run(early)
    data = h.data
    for period, ref in ((1, "halfTime:1"), (2, "fullTime:2")):
        clock, second = h.wait(data.period_end_at(MATCH, period))
        step = [n for n in h.narratives("home:casual") if n.stepId.endswith(ref)]
        assert step and (step[0].matchTime, step[0].timeSec) == (clock, second) and second < 59
    assert h.engine.cp["status"] == "complete"


def _settle(h):
    if h.engine.worker:
        h.wait(h.engine.worker)


def test_a_disabled_bucket_stops_and_is_caught_up_when_re_enabled():
    """Buckets are toggled in config: a disabled one gets nothing; re-enabled, it is caught up at once."""
    targets = MutableTargets("home:casual", "away:simple")
    h = Harness(targets=targets).run(MESSAGES[:30])
    targets.set("home:casual")
    h.wait(h.engine.sync_targets())
    written = len(h.narratives("away:simple"))
    later = MESSAGES.index(KEYS[1]) + 1
    h.run(MESSAGES[30:later])
    assert len(h.narratives("away:simple")) == written and h.narratives("home:casual")[-1].stepId.endswith(
        f"key:{KEYS[1].id}")
    targets.set("home:casual", "away:simple")
    h.wait(h.engine.sync_targets())
    _settle(h)
    assert [n.userType for n in h.narratives() if n.trigger.type == "catchUp"] == ["away:simple"]


def test_period_ended_uses_its_own_clock_and_waits_for_the_etl_end_row():
    """The SQL rows can trail the notification (Azure): the half-time step still runs at the End
    event's clock, but the end minute is summarised only once its End row is readable."""
    class Trailing(FixtureMatchData):
        lagging = True

        async def period_end_at(self, match_id, period_id):
            return None if self.lagging else await super().period_end_at(match_id, period_id)

        async def events(self, match_id, start, end, until_sec=59):
            rows = await super().events(match_id, start, end, until_sec)
            return [e for e in rows if not (self.lagging and e.get("typeId") == 30)]

    data = Trailing(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS)
    h = Harness(data=data, settings=Settings(retry_seconds=0.005, retry_max_seconds=0.01))
    data.lagging = False
    clock, second = h.wait(data.period_end_at(MATCH, 1))
    data.lagging = True
    at = next(i for i, m in enumerate(MESSAGES) if isinstance(m, PeriodChanged) and not m.started)
    ended = MESSAGES[at]
    messages = [m for m in MESSAGES[:at] if not (isinstance(m, MinuteClosed) and m.clock >= clock)]
    messages.append(PeriodChanged(ended.matchId, 1, False, ended.eventTime, clock, second))

    async def go():
        for m in messages:
            await h.engine.accept(m)
        await asyncio.sleep(0.2)  # the worker keeps retrying the end minute
    h.wait(go())
    assert h.engine.cp["periodEnds"]["1"] == clock.key and h.engine.cp["closedThrough"] == clock.key
    assert not [n for n in h.narratives() if n.trigger.type == "halfTime"]
    data.lagging = False
    _settle(h)
    half = [n for n in h.narratives("home:casual") if n.trigger.type == "halfTime"]
    assert [(n.matchTime, n.timeSec) for n in half] == [(clock, second)]


def test_an_excerpt_keeps_its_supported_sentences_when_one_claim_still_fails():
    """repair.author_trim: a sentence whose cause claim fails after the rewrite is removed, the rest is written;
    with author_trim off the whole excerpt is dropped as before."""
    from narrative_engine.analysis.policy import ShippedPolicy
    from doubles.fake_decisions import FakeDecisions

    def run(trim):
        h = Harness(targets=StaticTargets(default_targets()[:1]))
        policy = json.loads((Path(__file__).parents[1] / "narrative_engine" / "analysis" / "storyline-policy.json").read_text())
        policy["repair"]["author_trim"] = trim
        h.engine.policy = ShippedPolicy(policy)
        h.engine.decisions = FakeDecisions(rule=lambda key, question, state: (
            (0.0 if key.endswith("_support") else 0.9) if "pressing won it" in question.instructions.split("\n")[0]
            and "_causal" in key else 0.0))
        first_goal = MESSAGES.index(KEYS[0])
        h.run(MESSAGES[:first_goal])
        real = h.agents.author

        async def author(variables, prompt=None, feedback=None):
            result = await real(variables, prompt)
            return replace(result, text=f"{result.text.rstrip('.')}. Riverside's pressing won it.")
        h.agents.author = author
        h.run([KEYS[0]])
        step = f"{MATCH}:key:{KEYS[0].id}"
        return [n.text for n in h.narratives(default_targets()[0]["bucket_id"]) if n.stepId == step]
    kept = run(True)
    assert len(kept) == 1 and kept[0] and "pressing won it" not in kept[0]
    assert run(False) == []


def test_a_trimmed_excerpt_is_checked_again_as_a_whole():
    """After a trim a kept sentence follows a different one ("they" may now mean someone else); it is asked again
    with its new neighbour, and the excerpt is dropped when it no longer passes."""
    from narrative_engine.analysis.policy import ShippedPolicy
    from doubles.fake_decisions import FakeDecisions

    def fails(question):
        first = question.instructions.split("\n")[0]
        sentence = first.split('"')[1]
        return sentence == "Riverside's pressing won it." or (
            sentence == "They dominated it." and "Riverside's pressing" not in first)
    h = Harness(targets=StaticTargets(default_targets()[:1]))
    policy = json.loads((Path(__file__).parents[1] / "narrative_engine" / "analysis" / "storyline-policy.json").read_text())
    policy["repair"]["author_trim"] = True
    h.engine.policy = ShippedPolicy(policy)
    h.engine.decisions = FakeDecisions(rule=lambda key, question, state: (
        (0.0 if key.endswith("_support") else 0.9) if "_causal" in key and fails(question) else 0.0))
    h.run(MESSAGES[:MESSAGES.index(KEYS[0])])
    real = h.agents.author

    async def author(variables, prompt=None, feedback=None):
        result = await real(variables, prompt)
        return replace(result, text=f"{result.text.rstrip('.')}. Riverside's pressing won it. They dominated it.")
    h.agents.author = author
    h.run([KEYS[0]])
    step = f"{MATCH}:key:{KEYS[0].id}"
    assert [n for n in h.narratives(default_targets()[0]["bucket_id"]) if n.stepId == step] == []


def test_rejected_observations_get_one_repair_turn():
    from test_graphql_data import FIXTURE as WITH_TRENDS  # the same match with the ETL's reference trends
    h = Harness(data=WITH_TRENDS, targets=StaticTargets(default_targets()[:1]))
    real, asked = h.agents.analyse, []

    async def analyse(variables, prompt=None, feedback=None):
        result = await real(variables, prompt)
        if not (observations := json.loads(result.text)["observations"]):
            return result
        good = observations[0]
        bad = {**good, "label": "Made-up number", "storyline": "open", "headline": f"{good['headline']} 99"}
        if feedback:
            asked.append(feedback)
            fixed = {**bad, "headline": good["headline"]} if len(asked) == 1 else bad  # fixed only the first time
            return replace(result, text=json.dumps({"observations": [fixed]}))
        return replace(result, text=json.dumps({"observations": [good, bad]}))
    h.agents.analyse = analyse
    h.run(MESSAGES[:len(MESSAGES) // 2])
    analyses = [a for a in h.wait(h.store.analyses(MATCH)) if a["retried"]]
    assert len(analyses) >= 2 and ' 99", ' in asked[0][0] and "uses numbers not in its evidence: 99" in asked[0][1]
    first, second = analyses[:2]
    assert [o["label"] for o in first["observations"]][-1] == "Made-up number" and first["rejected"] == []
    assert len(second["rejected"]) == 1 and len(second["retried"]) == 1


def test_an_ungrounded_excerpt_is_rewritten_once_then_dropped():
    targets = default_targets()[:2]
    h = Harness(targets=StaticTargets(targets))
    first_goal = MESSAGES.index(KEYS[0])
    h.run(MESSAGES[:first_goal])
    real, asked = h.agents.author, []
    fixed, dropped = (t["bucket_id"] for t in targets)

    async def author(variables, prompt=None, feedback=None):
        result = await real(variables, prompt)
        if feedback:
            asked.append((variables["bucket_id"], feedback[1]))
        if variables["bucket_id"] == dropped or not feedback:
            return replace(result, text=f"{result.text} They have had 99 shots.")
        return result
    h.agents.author = author
    h.run([KEYS[0]])
    step = f"{MATCH}:key:{KEYS[0].id}"
    assert sorted(asked) == [(dropped, ANY), (fixed, ANY)] and "99" in asked[0][1]
    assert h.narratives(fixed)[-1].stepId == step and "99" not in h.narratives(fixed)[-1].text
    assert all(n.stepId != step for n in h.narratives(dropped))
