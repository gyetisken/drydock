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
    assert (dollars, turns, overran) == (0.4, 7, "")
    assert not fake.terminated


def test_a_worker_that_goes_quiet_is_stopped():
    """The actual failure: output stops, the pipe stays open, and reading it
    blocks forever. The timer runs on its own thread for exactly that."""
    fake = Fake(['{"num_turns": 1}\n'] * 50, linger=0.1)
    started = time.time()
    _dollars, _turns, overran = engine(minutes=0.01)._read(fake, None)
    assert overran == "clock"
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


class TestCountingTurns:
    """A worker reports its own turn count only in its final message. One
    that was stopped by the clock therefore reported nought turns after
    twelve minutes of visible work - wrong, and the opposite of useful in
    the one message where the number mattered."""

    def test_turns_are_counted_as_they_happen(self):
        import json

        from drydock.engines import ClaudeCodeEngine

        lines = [json.dumps({"type": "assistant", "message": {"content": []}})] * 5
        _, turns, _ = ClaudeCodeEngine()._read(_Says(lines), None)
        assert turns == 5

    def test_the_worker_s_own_count_wins_when_it_is_larger(self):
        """It knows about turns that produced no assistant message."""
        import json

        from drydock.engines import ClaudeCodeEngine

        lines = [
            json.dumps({"type": "assistant", "message": {"content": []}}),
            json.dumps({"type": "result", "num_turns": 9, "total_cost_usd": 0.4}),
        ]
        _, turns, _ = ClaudeCodeEngine()._read(_Says(lines), None)
        assert turns == 9

    def test_a_count_that_arrives_low_does_not_undo_what_was_seen(self):
        import json

        from drydock.engines import ClaudeCodeEngine

        lines = [json.dumps({"type": "assistant", "message": {"content": []}})] * 4 + [
            json.dumps({"type": "result", "num_turns": 1})
        ]
        _, turns, _ = ClaudeCodeEngine()._read(_Says(lines), None)
        assert turns == 4


class _Says:
    """A worker that emits these lines and then ends."""

    returncode = 0

    def __init__(self, lines):
        self.stdout = iter(lines)
        self.stderr = _Reader("")

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass

    def terminate(self):
        pass


class TestAWorkerThatStopsProducingAnything:
    """Working looks like a tool call every few seconds. Five minutes of
    complete silence is not a long turn; it is a worker that has come off
    the rails. One did exactly this and held an item for ten minutes before
    the twelve-minute clock reached it, and the whole of that was spent
    waiting for something that was never coming."""

    def test_it_is_stopped_before_the_long_clock_reaches_it(self, monkeypatch):
        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "QUIET_AFTER", 1000)
        monkeypatch.setattr(engines, "SILENT_LIMIT", 0.1)

        worker = _Silent(for_seconds=0.5)
        _, _, stopped = engines.ClaudeCodeEngine(minutes=10)._read(worker, None)
        assert stopped == "silence"

    def test_the_two_reasons_are_told_apart(self, monkeypatch):
        """'This item is too large' and 'this worker stopped working' call
        for opposite responses, and both used to read as the same sentence."""
        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "SILENT_LIMIT", 1000)

        worker = _Silent(for_seconds=0.5)
        _, _, stopped = engines.ClaudeCodeEngine(minutes=0.002)._read(worker, None)
        assert stopped == "clock"

    def test_a_worker_that_keeps_talking_is_not_stopped(self, monkeypatch):
        import json

        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "SILENT_LIMIT", 0.1)

        lines = [json.dumps({"type": "assistant", "message": {"content": []}})] * 3
        _, _, stopped = engines.ClaudeCodeEngine(minutes=10)._read(_Says(lines), None)
        assert stopped == ""


class TestTheWorkersOutputIsNotTrusted:
    """It is a wire format from another program. The only safe assumption
    about any field in it is that the line parsed as JSON."""

    def test_a_null_turn_count_does_not_crash_the_reader(self):
        import json

        from drydock.engines import ClaudeCodeEngine

        lines = [json.dumps({"type": "result", "num_turns": None})]
        _, turns, _ = ClaudeCodeEngine()._read(_Says(lines), None)
        assert turns == 0

    def test_a_null_price_does_not_become_the_price(self):
        import json

        from drydock.engines import ClaudeCodeEngine

        lines = [
            json.dumps({"type": "result", "total_cost_usd": 0.4}),
            json.dumps({"type": "result", "total_cost_usd": None}),
        ]
        dollars, _, _ = ClaudeCodeEngine()._read(_Says(lines), None)
        assert dollars == 0.4

    def test_a_line_that_is_not_an_object_is_skipped(self):
        from drydock.engines import ClaudeCodeEngine

        _, turns, _ = ClaudeCodeEngine()._read(_Says(["{ not json", "[]", ""]), None)
        assert turns == 0


class TestTellingTheTwoKindsOfStopApart:
    """An item the engineer could not do and a worker that was taken away
    read the same from here - no report, a non-zero exit - and call for
    opposite responses."""

    def test_a_signal_is_a_worker_that_was_taken_away(self):
        from drydock.engines import _was_killed

        assert _was_killed(143)  # its runtime caught the signal and exited
        assert _was_killed(137)
        assert _was_killed(-15)  # or it was killed outright
        assert _was_killed(-9)

    def test_an_ordinary_failure_is_not(self):
        from drydock.engines import _was_killed

        assert not _was_killed(0)
        assert not _was_killed(1)
        assert not _was_killed(2)
        assert not _was_killed(127)
        assert not _was_killed(None)

    def test_a_worker_stopped_by_the_clock_is_not_counted_as_taken_away(self):
        """This program sent that signal, on purpose, and the item really
        did run out of time. Restarting it would run it out again."""
        from drydock.engines import _was_killed

        assert _was_killed(143)  # the signal, in isolation
        # and in context the engine reports died=False, because it knows it
        # was the one holding the clock. Pinned where that decision is made.


class TestWhoAskedItToStop:
    """A worker that died of a signal nobody here sent is a different
    problem from one this program stopped on purpose, and from outside the
    two were indistinguishable: an item ended with 'exited 143' and no
    account of who asked. Twice, on the same item, with no explanation
    available anywhere."""

    def test_a_signal_this_program_sent_is_remembered(self):
        from drydock.engines import _SIGNALLED, _asked_to_stop

        worker = _Silent(for_seconds=0)
        worker.pid = 4242
        _asked_to_stop(worker, "it ran out of its twelve minutes")

        assert _SIGNALLED.pop(4242) == "it ran out of its twelve minutes"

    def test_a_process_that_cannot_be_signalled_is_not_an_error(self):
        """It has already gone, which is the outcome that was wanted."""
        from drydock.engines import _asked_to_stop

        class Gone:
            pid = 1

            def terminate(self):
                raise OSError("no such process")

        _asked_to_stop(Gone(), "stopping")  # must not raise

    def test_a_worker_with_no_pid_is_not_an_error(self):
        from drydock.engines import _asked_to_stop

        class Odd:
            def terminate(self):
                pass

        _asked_to_stop(Odd(), "stopping")  # must not raise
