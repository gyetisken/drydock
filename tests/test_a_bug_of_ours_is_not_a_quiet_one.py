"""A gate that died left no trace, and the item shipped anyway.

Two separate silences, in the same handful of lines.

The first: `_judge` runs the gates in a pool and reads their futures. A
future that raised was reported as one line of feed text and then
`continue`d past - so nothing about it reached the result. The item was
judged on whatever gates survived, and a required check that crashed was
indistinguishable from a required check that passed. `unverified` existed
for exactly this and was fed only by the critic's own lost verdicts.

The second: every line `execute` emits went through one closure bound to
the Engineer before the loop started. So the critic failing to start a
browser, a reviewer dying mid-diff and an `AttributeError` of ours all
appeared on the Engineer's desk, in a tool log, while the desk that
actually failed sat idle and clean.

And under both of them, the same missing distinction: `f"{exc}"` cannot
tell a machine with no browser from a `TypeError` in this program's own
code, and only one of those is somebody's to fix. Now the kind is asked,
ours is named as ours with the line it came from, and its traceback is
printed - because for a bug of ours the traceback is the only thing that
fixes it.
"""

import inspect
from pathlib import Path

from drydock import blame, orchestrate, session

SOURCE = Path("src/drydock/orchestrate.py").read_text()


class TestWhoseFaultItWas:
    def test_our_own_mistakes_are_ours(self):
        for exc in (
            AttributeError("no such thing"),
            TypeError("wrong shape"),
            KeyError("absent"),
            IndexError("past the end"),
            NameError("never bound"),
            UnboundLocalError("read before written"),
            AssertionError("not so"),
            ZeroDivisionError("by zero"),
            NotImplementedError("not yet"),
        ):
            assert blame.is_ours(exc), exc

    def test_the_world_being_unavailable_is_not(self):
        for exc in (
            OSError("no such file"),
            TimeoutError("took too long"),
            RuntimeError("the worker stopped"),
            LookupError("no browser"),
            ConnectionError("refused"),
        ):
            assert not blame.is_ours(exc), exc

    def test_a_bad_payload_is_not_called_our_bug(self):
        """A model that answered with broken JSON raises `ValueError`.
        That is a worker's doing, and calling it ours would point every
        malformed answer at this program."""
        import json

        assert not blame.is_ours(ValueError("not json"))
        try:
            json.loads("{oh no")
        except ValueError as exc:
            assert not blame.is_ours(exc)


class TestWhatItSays:
    def _raised(self, how):
        try:
            how()
        except Exception as exc:  # noqa: BLE001 - the subject of the test
            return exc
        raise AssertionError("nothing was raised")

    def test_ours_is_named_as_ours(self):
        exc = self._raised(lambda: blame.where(1, 2))  # type: ignore[call-arg]
        said = blame.plainly(exc)
        assert "a bug in drydock" in said
        assert "not in the work" in said
        assert "TypeError" in said

    def test_ours_carries_the_line_it_came_from(self):
        """The deepest frame inside this package. The top of a traceback
        is the orchestrator calling something, which is never the line
        anybody needs."""
        exc = self._raised(lambda: orchestrate._station_of(None))
        spot = blame.where(exc)
        assert spot.startswith("orchestrate.py:")
        assert spot.split(":")[1].isdigit()
        assert spot in blame.plainly(exc)

    def test_a_world_failure_is_said_plainly(self):
        said = blame.plainly(TimeoutError("took too long"))
        assert said == "TimeoutError: took too long"
        assert "drydock" not in said

    def test_an_exception_with_no_message_still_says_something(self):
        assert "no message" in blame.plainly(RuntimeError())

    def test_a_frame_outside_this_package_is_not_claimed(self):
        assert blame.where(TypeError("never raised")) == ""


class TestTheTraceReachesSomebody:
    def test_ours_is_printed(self, capsys):
        try:
            {}["absent"]
        except KeyError as exc:
            blame.report("critic", exc)
        said = capsys.readouterr().err
        assert "drydock bug" in said
        assert "KeyError" in said
        assert "Traceback" in said

    def test_the_station_that_hit_it_is_named(self, capsys):
        try:
            raise AttributeError("no such thing")
        except AttributeError as exc:
            blame.report("reviewer", exc)
        assert "reviewer" in capsys.readouterr().err

    def test_a_world_failure_does_not_print_a_traceback(self, capsys):
        """A machine with no browser does not need thirty lines to
        explain itself, and the console is somebody's to read."""
        try:
            raise TimeoutError("took too long")
        except TimeoutError as exc:
            blame.report("critic", exc)
        assert capsys.readouterr().err == ""

    def test_whoever_is_watching_is_told_either_way(self):
        heard = []
        for exc in (TypeError("ours"), TimeoutError("theirs")):
            blame.report("critic", exc, lambda who, what: heard.append((who, what)))
        assert [who for who, _ in heard] == ["critic", "critic"]
        assert len(heard) == 2

    def test_a_broken_feed_is_not_the_failure(self):
        def refuse(who, what):
            raise RuntimeError("the page is gone")

        assert blame.report("critic", TimeoutError("x"), refuse)

    def test_the_note_goes_in_front(self):
        said = blame.report("critic", TimeoutError("x"), note="could not look at it")
        assert said.startswith("could not look at it: ")

    def test_nothing_here_raises(self):
        """Including on things that are not exceptions at all."""
        assert blame.where(None) == ""
        assert blame.trace(None) == ""


class TestADeadGateIsAMissingCheck:
    def test_it_is_recorded_rather_than_skipped(self):
        source = inspect.getsource(orchestrate._judge)
        block = source[source.index("one gate failing is not the item failing") :]
        assert "unverified.append(" in block[:700]

    def test_it_is_named_with_the_station_that_died(self):
        source = inspect.getsource(orchestrate._judge)
        block = source[source.index("one gate failing is not the item failing") :]
        assert 'f"{name}: "' in block[:700]
        assert 'blame.report(name, exc, on_event, note="could not finish")' in block

    def test_an_unverified_check_still_blocks_delivery(self):
        """The whole point. This is the path that discards the work and
        reports it, and it must still be reached."""
        assert "if verdict.passed and unverified:" in SOURCE
        block = SOURCE[SOURCE.index("if verdict.passed and unverified:") :][:1200]
        assert "here.discard()" in block
        assert "Outcome.BLOCKED" in block
        assert "a required check could not be completed" in block

    def test_it_is_judged_before_anything_is_committed(self):
        assert SOURCE.index("if verdict.passed and unverified:") < SOURCE.index(
            "if verdict.passed and not refusal:"
        )

    def test_a_lost_verdict_is_still_unverified_too(self):
        source = inspect.getsource(orchestrate._judge)
        assert 'unverified.append(f"{name}: {answer.failed}")' in source

    def test_the_critic_still_says_what_it_could_not_do(self):
        source = inspect.getsource(orchestrate._show_it)
        assert 'note="could not look at it"' in source
        assert "failed=said" in source
        assert "approved=False" in source


class TestItIsShownUnderTheRightStation:
    def test_the_unverified_report_asks_who(self):
        block = SOURCE[SOURCE.index("if verdict.passed and unverified:") :][:1200]
        assert "_station_of(unverified[0])" in block
        assert 'on_gate(item, "critic"' not in block

    def test_only_a_real_station_is_shown_as_one(self):
        assert orchestrate._station_of("reviewer: could not finish") == "reviewer"
        assert orchestrate._station_of("inspector: x") == "inspector"
        assert orchestrate._station_of("critic: x") == "critic"

    def test_an_untagged_line_falls_back_rather_than_inventing_a_desk(self):
        assert orchestrate._station_of("could not look at it: boom") == "critic"
        assert orchestrate._station_of("") == "critic"

    def test_the_loop_no_longer_speaks_only_as_the_engineer(self):
        source = inspect.getsource(session.Session._work_the_plan)
        assert "on_event=self._station_event()" in source
        assert 'on_event=self._agent_event("Engineer")' not in source

    def test_every_station_has_a_desk(self):
        for name in orchestrate.GATES:
            assert name in session.DESKS

    def test_the_desks_are_the_ones_the_window_draws(self):
        office = Path("src/drydock/static/office.js").read_text()
        for desk in set(session.DESKS.values()):
            assert f'id: "{desk}"' in office

    def test_an_unknown_name_goes_to_the_engineer(self):
        """Rather than to a desk that does not exist, which the office
        would create and nobody would ever look at."""
        heard = []

        class Fake:
            _agent_event = session.Session._agent_event
            feed = type("F", (), {"emit": lambda self, *a, **k: heard.append(k)})()

        route = session.Session._station_event(Fake())
        route("something else", "a line")
        assert heard[0]["agent"] == "Engineer"

    def test_a_named_station_goes_to_its_own_desk(self):
        heard = []

        class Fake:
            _agent_event = session.Session._agent_event
            feed = type("F", (), {"emit": lambda self, *a, **k: heard.append(k)})()

        route = session.Session._station_event(Fake())
        route("critic", "could not look at it")
        assert heard[0]["agent"] == "Critic"
        assert heard[0]["detail"] == "could not look at it"
