"""The deadline existed for two days and nothing could ask for one.

`a700db9` built it: a timer that ends the workers, checkpoints that stop
anything new from starting, and `minutes` on the API, on resume and on
`drydock run`. Every one of those is a thing somebody types. The window,
which is how this is actually used, had no box - so in practice every
run was still unbounded, and the only way to end one on time was a
person watching the clock and sending a stop by hand. That is exactly
what happened in Corso B, at forty-two minutes against an approved
thirty-five.

So the box is there, next to the model and the engine, empty by default
and remembered when it is set. Empty means no deadline. And when one
fires it is said in its own right rather than as another stop: "it was
stopped" and "it ran out of time" are different things to read
afterwards - one was somebody's decision, the other was the bound they
set.
"""

from pathlib import Path

from drydock.session import Session
from drydock.web import StartJob

JS = Path("src/drydock/static/chat.js").read_text()


def flat(text: str) -> str:
    """One line, so an assertion is not a claim about where it wraps."""
    return " ".join(text.split())


PAGE = Path("src/drydock/web.py").read_text()
CSS = Path("src/drydock/static/app.css").read_text()


class TestTheBoxExists:
    def test_the_page_has_one(self):
        assert 'id="minutes"' in PAGE

    def test_it_is_a_number_with_sane_bounds(self):
        box = PAGE[PAGE.index('id="minutes"') - 120 : PAGE.index('id="minutes"') + 200]
        assert 'type="number"' in box
        assert 'min="1"' in box

    def test_it_sits_with_the_other_choices(self):
        """Model, engine and now how long. The same row, because they
        are the three things you pick before sending."""
        assert PAGE.index('id="pick-engine"') < PAGE.index('id="minutes"')
        assert PAGE.index('id="minutes"') < PAGE.index('id="go"')

    def test_it_says_what_it_does(self):
        assert "end the run after this many minutes" in PAGE

    def test_empty_reads_as_no_deadline(self):
        """The placeholder is an infinity sign rather than a number, so
        an empty box does not look like a value somebody chose."""
        box = PAGE[PAGE.index('id="minutes"') : PAGE.index('id="minutes"') + 220]
        assert "&#8734;" in box


class TestWhatItSends:
    def test_the_request_carries_it(self):
        assert "minutes: deadlineAsked()" in JS

    def test_an_empty_box_sends_zero(self):
        said = JS[JS.index("function deadlineAsked(") :][:400]
        assert "asked > 0 ? asked : 0" in said

    def test_a_bad_number_is_not_a_deadline(self):
        """Not a deadline that has already expired, which is what a
        negative would be if it were passed through."""
        said = JS[JS.index("function deadlineAsked(") :][:400]
        assert "Number.isFinite(asked)" in said

    def test_the_api_takes_it(self):
        assert "minutes" in StartJob.model_fields
        assert StartJob(project="/x", command="/do a").minutes == 0.0
        assert StartJob(project="/x", command="/do a", minutes=20).minutes == 20

    def test_the_session_refuses_nonsense_the_same_way(self):
        """Both ends agree: anything that is not a positive number means
        no deadline."""
        for bad in (0, -5, None):
            assert (
                Session(Path("/tmp"), "t", [], within_minutes=bad).within_minutes == 0
            )

    def test_it_is_remembered(self):
        said = JS[JS.index("function drawDeadline(") :][:600]
        assert 'localStorage.getItem("drydock.minutes")' in said
        assert 'localStorage.setItem("drydock.minutes"' in said

    def test_clearing_it_forgets_it(self):
        said = JS[JS.index("function drawDeadline(") :][:600]
        assert 'localStorage.removeItem("drydock.minutes")' in said

    def test_it_is_drawn_when_the_window_loads(self):
        assert "drawDeadline();" in JS


class TestWhenItFires:
    def test_the_window_knows_the_event(self):
        assert '"deadline": (e) => {' in JS

    def test_it_is_said_apart_from_an_ordinary_stop(self):
        assert '"stopping": (e) => {' in JS
        assert JS.index('"stopping": (e)') < JS.index('"deadline": (e)')
        said = JS[JS.index('"deadline": (e)') :][:1400]
        assert "Time is up" in said

    def test_it_says_what_happened_to_the_work(self):
        said = flat(JS[JS.index('"deadline": (e)') :][:1400])
        assert "What landed before this is committed and stays" in said
        assert "the item in flight was thrown away unfinished" in said

    def test_it_says_the_workers_were_ended(self):
        said = flat(JS[JS.index('"deadline": (e)') :][:1400])
        assert "workers of this run have been ended" in said

    def test_it_is_marked_in_the_style(self):
        assert ".body.deadline" in CSS

    def test_the_session_emits_it(self):
        import inspect

        source = inspect.getsource(Session._out_of_time)
        assert 'self.feed.emit("deadline"' in source


class TestCancellationIsUnchanged:
    def test_the_timer_still_ends_the_workers(self):
        import inspect

        source = inspect.getsource(Session._out_of_time)
        assert "self.stop(now=True)" in source

    def test_an_ordinary_stop_still_leaves_the_worker_to_finish(self):
        import inspect

        source = inspect.getsource(Session.stop)
        assert "stop_workers(self.repo) if now else 0" in source

    def test_the_clock_is_still_cancelled_when_the_run_ends(self):
        import inspect

        source = inspect.getsource(Session._work)
        assert "self._stop_the_clock()" in source

    def test_a_fired_deadline_does_not_fire_twice(self):
        import inspect

        source = inspect.getsource(Session._out_of_time)
        assert "if self.stopping:" in source

    def test_the_stop_checks_in_the_loop_are_untouched(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert source.count("_stopping(should_stop)") >= 5
