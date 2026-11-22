"""Pressing stop did nothing, for up to twelve minutes.

`session.stop()` sets a flag that is read wherever work is about to
start, and leaves the worker in flight to finish into a clean tree. That
is the right default and it was the only thing on offer. An engineer has
twelve minutes for an attempt, so "stop" could mean twelve minutes of
watching nothing stop.

And the window disabled the button on the first press, so there was no
second thing to say. Somebody who meant "end it" got "stopping after the
current item", a dead button, and a worker that kept writing. Watched
happen on the LUMI run: stop was pressed, the API answered `{"ok":true}`,
and the worker was still going two minutes later.

The machinery to end one already existed and was already tested - the
deadline uses it. It just had no way to be asked for by a person. Now
the first press asks and the second tells, and the button stays alive
in between to be told with.
"""

from pathlib import Path

from drydock.session import Session

JS = Path("src/drydock/static/chat.js").read_text()
WEB = Path("src/drydock/web.py").read_text()


class TestTheEndpointCanEndIt:
    def test_it_takes_now(self):
        import inspect

        from drydock.web import stop

        assert "now" in inspect.signature(stop).parameters
        assert inspect.signature(stop).parameters["now"].default is False

    def test_it_passes_it_on(self):
        import inspect

        from drydock.web import stop

        assert "session.stop(now=now)" in inspect.getsource(stop)

    def test_asking_is_still_the_default(self):
        """The kind thing, and what somebody wants almost always."""
        import inspect

        from drydock.web import stop

        said = " ".join(inspect.getsource(stop).split())
        assert "the worker in flight finishes into a clean tree" in said

    def test_an_unknown_run_is_still_said_rather_than_crashed(self):
        from drydock.web import stop

        assert stop("nope") == {"ok": False, "reason": "no such run"}


class TestTheTwoKindsOfStopAreUnchangedUnderneath:
    def test_asking_leaves_the_worker_alone(self):
        import inspect

        assert "stop_workers(self.repo) if now else 0" in inspect.getsource(
            Session.stop
        )

    def test_telling_ends_the_workers(self):
        import inspect

        said = inspect.getsource(Session.stop)
        assert "self.stopping = True" in said
        assert "stop_workers(self.repo)" in said

    def test_the_deadline_still_uses_the_same_one(self):
        import inspect

        assert "self.stop(now=True)" in inspect.getsource(Session._out_of_time)

    def test_the_checkpoints_in_the_loop_are_untouched(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert source.count("_stopping(should_stop)") >= 5

    def test_a_killed_worker_is_still_not_revived_while_stopping(self):
        """Otherwise ending one extends the run instead of ending it."""
        source = Path("src/drydock/orchestrate.py").read_text()
        assert 'if report.get("died") and _stopping(should_stop):' in source


class TestTheButtonStaysAlive:
    def test_the_first_press_does_not_disable_it(self):
        said = JS[JS.index("async function halt()") :][:900]
        assert 'if (now) $("go").disabled = true;' in said

    def test_the_second_press_is_the_one_that_ends_it(self):
        said = JS[JS.index("async function halt()") :][:900]
        assert "const now = S.stopAsked;" in said
        assert "S.stopAsked = true;" in said
        assert "?now=true" in said

    def test_it_says_there_is_a_second_press(self):
        said = JS[JS.index("async function halt()") :][:900]
        assert "press again to end it now" in said

    def test_the_tooltip_changes_with_it(self):
        said = JS[JS.index("function running(on, what)") :][:800]
        assert 'S.stopAsked ? "ending it now" : "stop after the current item"' in said

    def test_a_finished_run_forgets_it_was_asked(self):
        """Otherwise the next run's first press would end it outright."""
        said = JS[JS.index("function running(on, what)") :][:400]
        assert 'if (!on) { S.stopAsked = false; $("go").disabled = false; }' in said

    def test_the_flag_starts_false(self):
        assert "stopAsked: false }" in JS

    def test_why_is_written_down(self):
        at = JS.index("// Two presses, because there are two honest answers")
        # Comment markers out, so the assertion is not a claim about
        # where the prose wraps.
        said = " ".join(JS[at:][:900].replace("//", " ").split())
        assert "had no way to say it again" in said
        assert "watched an engineer run for its full twelve minutes" in said
