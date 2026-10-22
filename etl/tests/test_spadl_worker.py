"""SPADL post-processor loop: polls back off while idle; with an activity check (Azure: Event Hubs partition
properties) it closes SQL after idle_seconds and wakes only when new input arrives."""
from spadl.worker import SpadlWorker


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Stop:  # threading.Event stand-in: waits advance the clock and are recorded
    def __init__(self, clock):
        self.clock, self.waits, self.stopped = clock, [], False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.waits.append(seconds)
        self.clock.now += seconds
        return self.stopped


class Repo:
    closed = 0

    def close(self):
        self.closed += 1

    def rollback(self):
        pass


def run(steps, activity=None):
    clock, repo = Clock(), Repo()
    stop, script = Stop(clock), iter(steps)
    worker = SpadlWorker(repo, poll_seconds=0.5, max_poll_seconds=4, idle_seconds=10, activity=activity, clock=clock)

    def step():
        result = next(script, None)
        if result is None:
            stop.stopped = True
            return {}
        return result

    worker.step = step
    worker.run(stop)
    return stop.waits, repo.closed


def test_idle_polls_back_off_and_reset_after_work():
    waits, closed = run([{"m": 3}, {}, {}, {}, {}, {}, {}, {"m": 1}, {}])
    assert waits == [0.5, 1, 2, 4, 4, 4, 0.5, 1] and closed == 0  # No activity check: SQL stays open.


def test_long_idle_closes_sql_until_the_hub_receives():
    marks = iter(["a", "a", "a", "b"])  # the mark, two unchanged checks, then a feed sends
    waits, closed = run([{"m": 3}, {}, {}, {}, {}, {}, {}, {"m": 1}], activity=lambda: next(marks))
    assert waits[:5] == [0.5, 1, 2, 4, 4]  # 11.5 s idle >= 10 s
    assert waits[5:8] == [4, 4, 4] and closed == 1  # asleep: only the activity check runs
    assert waits[8:] == [0.5]  # awake: polling SQL from poll_seconds again


def test_a_failing_activity_check_keeps_polling_sql():
    def broken():
        raise OSError("hub unreachable")
    waits, closed = run([{"m": 3}, {}, {}, {}, {}, {}, {}, {}], activity=broken)
    assert closed == 0 and all(w <= 4 for w in waits)
