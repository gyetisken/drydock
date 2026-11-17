"""A worker that goes quiet must not stall the run.

Turns bound how much a worker does. Nothing bounded how long it took, so a
worker that stopped producing output held a run open with no end to it - the
page still said 'working', and it would have said that tomorrow.
"""

import subprocess
import time

from drydock.engines import ClaudeCodeEngine


class Fake:
    """Enough of a Popen to drive the reader."""

    def __init__(self, lines, linger=0.0):
        self._lines = iter(lines)
        self._linger = linger
        self.returncode = None
        self.killed = False
        self.terminated = False
        self.stdout = self

    def __iter__(self):
        return self

    def __next__(self):
        line = next(self._lines)
        if self._linger:
            time.sleep(self._linger)
        return line

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self._lines = iter([])

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("x", timeout or 0)
        return self.returncode


def engine(minutes=0.02):
    made = ClaudeCodeEngine.__new__(ClaudeCodeEngine)
    made.seconds = minutes * 60
    return made


def test_a_worker_that_answers_is_read_normally():
    fake = Fake(['{"total_cost_usd": 0.4, "num_turns": 7}\n'])
    dollars, turns, overran = engine(minutes=5)._read(fake, None)
    assert (dollars, turns, overran) == (0.4, 7, False)
    assert not fake.terminated


def test_a_worker_that_goes_quiet_is_stopped():
    """The actual failure: output stops, the pipe stays open, and reading it
    blocks forever. The timer runs on its own thread for exactly that."""
    fake = Fake(['{"num_turns": 1}\n'] * 50, linger=0.1)
    started = time.time()
    _dollars, _turns, overran = engine(minutes=0.01)._read(fake, None)
    assert overran
    assert fake.terminated
    assert time.time() - started < 5


def test_a_worker_that_will_not_terminate_is_killed():
    fake = Fake([])
    fake.returncode = None
    engine(minutes=5)._read(fake, None)
    assert fake.killed


class TestAWorkerThatGoesQuiet:
    """A worker can spend minutes inside a single turn. From outside, that
    is indistinguishable from a hang, and a spinner answers neither
    question. One of these went nine minutes without a word on a live run
    while the window showed it working, which is the one failure this
    program must not have: it looks exactly like working."""

    def test_it_says_how_long_it_has_been_quiet(self, monkeypatch):
        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "QUIET_AFTER", 0.1)

        said: list[tuple[str, str]] = []
        worker = _Silent(for_seconds=0.4)
        engines.ClaudeCodeEngine(minutes=10)._read(
            worker, lambda kind, text: said.append((kind, text))
        )

        assert any("still working" in text for _, text in said)
        assert any("before it is stopped" in text for _, text in said)

    def test_a_worker_that_keeps_talking_is_left_alone(self, monkeypatch):
        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "QUIET_AFTER", 5)

        said: list[tuple[str, str]] = []
        worker = _Silent(for_seconds=0.3)
        engines.ClaudeCodeEngine(minutes=10)._read(
            worker, lambda kind, text: said.append((kind, text))
        )

        assert not any("still working" in text for _, text in said)


class _Silent:
    """A worker that says nothing at all and then ends."""

    returncode = 0

    def __init__(self, for_seconds: float):
        self.seconds = for_seconds
        self.stdout = self
        self.stderr = _Reader("")

    def __iter__(self):
        import time as real

        real.sleep(self.seconds)
        return iter([])

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass

    def terminate(self):
        pass


class _Reader:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text
