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
        assert any("on one step" in text for _, text in said)

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


class TestItMeasuresWhatSomebodyWouldSee:
    """A worker streams steadily through one long turn and shows nothing a
    person recognises as progress. The heartbeat was watching the pipe, so
    it stayed quiet through two and a half minutes of empty window - it was
    answering 'is it alive', which was not the question."""

    def test_a_streaming_worker_showing_nothing_is_still_reported(self, monkeypatch):
        import json

        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "QUIET_AFTER", 0.15)
        monkeypatch.setattr(engines, "SILENT_LIMIT", 1000)

        said: list[tuple[str, str]] = []
        # Lines that parse and carry nothing worth showing: the shape a long
        # turn actually takes on the wire.
        lines = [json.dumps({"type": "stream_event", "n": i}) for i in range(40)]
        engines.ClaudeCodeEngine(minutes=10)._read(
            _Dribbles(lines, gap=0.03), lambda kind, text: said.append((kind, text))
        )

        assert any("on one step" in text for _, text in said)

    def test_a_worker_showing_things_is_left_alone(self, monkeypatch):
        import json

        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "QUIET_AFTER", 0.15)
        monkeypatch.setattr(engines, "SILENT_LIMIT", 1000)

        said: list[tuple[str, str]] = []
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Write"}]},
                }
            )
            for _ in range(40)
        ]
        engines.ClaudeCodeEngine(minutes=10)._read(
            _Dribbles(lines, gap=0.03), lambda kind, text: said.append((kind, text))
        )

        assert not any("on one step" in text for _, text in said)


class _Dribbles:
    """A worker whose output arrives slowly, a line at a time."""

    returncode = 0

    def __init__(self, lines, gap: float):
        self.lines, self.gap = lines, gap
        self.stdout = self
        self.stderr = _Reader("")

    def __iter__(self):
        import time as real

        for line in self.lines:
            real.sleep(self.gap)
            yield line

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass

    def terminate(self):
        pass


class TestARetryIsGivenMoreThanTheAttemptBeforeIt:
    """It has more to do: the item, plus everything it was sent back for,
    read and dealt with one by one. Twelve minutes bounds an ordinary
    attempt and was being applied to the hardest one."""

    def test_a_first_attempt_gets_the_ordinary_clock(self, monkeypatch):
        assert _minutes_for(monkeypatch, retry_of="") == 12.0

    def test_a_retry_gets_longer(self, monkeypatch):
        assert _minutes_for(monkeypatch, retry_of="the critic sent it back") == 18.0

    def test_a_retry_gets_the_judgement_model(self, monkeypatch):
        """Another ten minutes of the same mistake costs more than the
        difference between the models."""
        assert _model_for(monkeypatch, retry_of="sent back") == "opus"
        assert _model_for(monkeypatch, retry_of="") == "sonnet"


def _built(monkeypatch, retry_of: str):
    """The engine the engineer would build, without running anything."""
    from drydock import engineer

    seen = {}

    class Fake:
        def __init__(self, model="opus", max_turns=60, minutes=12.0):
            seen["model"] = model
            seen["minutes"] = minutes

        def work(self, *a, **k):
            class Result:
                done = True
                summary = ""
                files_changed: list = []
                noticed: list = []
                question = ""
                died = False
                dollars = 0.0
                turns = 1

            return Result()

    monkeypatch.setattr(engineer, "ClaudeCodeEngine", Fake)
    monkeypatch.setattr(engineer, "briefing", lambda skills, role: "")
    from drydock.models import Item

    engineer.work(
        __import__("pathlib").Path("/tmp"),
        "a task",
        Item(id=1, title="t", rationale="r", files=[], verify_with="tests"),
        "npm run build",
        retry_of=retry_of,
        engine="claude",
        model="opus",
    )
    return seen


def _minutes_for(monkeypatch, retry_of: str) -> float:
    return _built(monkeypatch, retry_of)["minutes"]


def _model_for(monkeypatch, retry_of: str) -> str:
    return _built(monkeypatch, retry_of)["model"]


class TestAWorkerNobodyIsWatching:
    """Some stations run with no event listener at all. The clock that
    decides whether a worker has stopped working only moved when something
    was handed to a listener, so with none it never moved and the worker
    would be stopped five minutes in for working quietly."""

    def test_it_is_not_stopped_for_having_no_audience(self, monkeypatch):
        import json

        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "SILENT_LIMIT", 0.2)

        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Write"}]},
                }
            )
            for _ in range(30)
        ]
        _, _, stopped = engines.ClaudeCodeEngine(minutes=10)._read(
            _Dribbles(lines, gap=0.03), None
        )
        assert stopped == ""


def test_the_clock_it_reports_is_the_one_it_was_given():
    """A retry is given eighteen minutes and was being told it had twelve."""
    from drydock.engines import ClaudeCodeEngine

    assert ClaudeCodeEngine(minutes=18.0).seconds == 18 * 60


class TestBusyAgainstStuck:
    """From outside they are identical: no tool call, no text, no result,
    for minutes. One is writing a stylesheet and the other is waiting on a
    connection that will never answer. The partial chunks are the only
    thing that tells them apart, and getting it wrong in either direction
    is expensive - one way a stalled worker holds an item for six minutes,
    the other way a worker is killed halfway through a long file."""

    def test_a_worker_writing_a_long_file_is_left_alone(self, monkeypatch):
        """It shows nothing anybody can read, and is plainly working."""
        import json

        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "QUIET_AFTER", 1000)
        monkeypatch.setattr(engines, "SILENT_LIMIT", 0.3)

        fragments = [
            json.dumps(
                {"type": "stream_event", "event": {"type": "content_block_delta"}}
            )
            for _ in range(40)
        ]
        _, _, stopped = engines.ClaudeCodeEngine(minutes=10)._read(
            _Dribbles(fragments, gap=0.02), None
        )
        assert stopped == ""

    def test_a_worker_producing_nothing_at_all_is_stopped(self, monkeypatch):
        from drydock import engines

        monkeypatch.setattr(engines, "QUIET_EVERY", 0.05)
        monkeypatch.setattr(engines, "QUIET_AFTER", 1000)
        monkeypatch.setattr(engines, "SILENT_LIMIT", 0.2)

        _, _, stopped = engines.ClaudeCodeEngine(minutes=10)._read(
            _Silent(for_seconds=0.6), None
        )
        assert stopped == "silence"

    def test_the_fragments_are_not_shown_to_anybody(self, monkeypatch):
        """Half a word is not progress a person can read."""
        import json

        from drydock import engines

        said: list[tuple[str, str]] = []
        fragments = [
            json.dumps(
                {"type": "stream_event", "event": {"type": "content_block_delta"}}
            )
            for _ in range(10)
        ]
        engines.ClaudeCodeEngine(minutes=10)._read(
            _Says(fragments), lambda kind, text: said.append((kind, text))
        )
        assert said == []

    def test_the_worker_is_asked_for_them(self):
        """Without the flag there are no fragments and the two cases are
        indistinguishable again."""
        import inspect

        from drydock import engines

        source = inspect.getsource(engines)
        assert source.count("--include-partial-messages") == 2
