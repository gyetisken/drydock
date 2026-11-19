"""The deadline existed and nothing could ask for one.

`Session.ends_in` was written, tested, and wired to nothing: no entry
point took a number of minutes, so every run still started with no
deadline and the only way to end one on time was a person watching the
clock. That is how the Corso B run came to need two stops and two kills
by hand at forty-two minutes against an approved thirty-five.

Three ways in and all three carry it now: the API that the window posts
to, the resume that picks a run back up, and `drydock run` on the command
line, which calls `execute` directly and has no session at all.

What is pinned here is the propagation and the cancellation. That a
deadline actually ends the workers and stops the retries is pinned in
test_stopping_actually_stops.py, which is the other half and the reason
this one is allowed to claim anything.
"""

import inspect
import threading
import time

import pytest

from drydock import cli, web
from drydock import session as session_module
from drydock import workspace as workspace_module
from drydock.session import Session


@pytest.fixture
def quiet(monkeypatch):
    """A session that never spawns its work thread."""
    monkeypatch.setattr(Session, "_work", lambda self, auto_run: None)


class TestTheSessionTakesOne:
    def test_none_by_default(self, tmp_path):
        assert Session(tmp_path, "t", []).within_minutes == 0.0

    def test_a_number_is_kept(self, tmp_path):
        assert Session(tmp_path, "t", [], within_minutes=35).within_minutes == 35.0

    def test_nonsense_is_not_a_deadline(self, tmp_path):
        """A negative or a None must read as "no deadline" rather than as
        one that has already expired."""
        assert Session(tmp_path, "t", [], within_minutes=-5).within_minutes == 0.0
        assert Session(tmp_path, "t", [], within_minutes=None).within_minutes == 0.0


class TestItIsArmedBeforeAnyWorker:
    def test_the_clock_starts_with_the_run(self, tmp_path, quiet):
        s = Session(tmp_path, "t", [], within_minutes=30)
        assert s._clock is None, "not before it is started"
        s.start()
        assert isinstance(s._clock, threading.Timer)
        s._stop_the_clock()

    def test_no_deadline_arms_nothing(self, tmp_path, quiet):
        s = Session(tmp_path, "t", [])
        s.start()
        assert s._clock is None

    def test_the_clock_is_armed_before_the_thread_is_made(self):
        """Everything that can start a worker happens inside the thread,
        so this ordering is the whole guarantee."""
        source = inspect.getsource(Session.start)
        assert source.index("self.ends_in(") < source.index("threading.Thread(")


class TestTheApiCarriesIt:
    def test_the_request_has_a_field(self):
        job = web.StartJob(project="/x", command="/do a thing")
        assert job.minutes == 0.0
        assert (
            web.StartJob(project="/x", command="/do a thing", minutes=35).minutes == 35
        )

    def test_it_is_handed_to_the_workspace(self):
        assert "body.minutes," in inspect.getsource(web.start)

    def test_the_workspace_hands_it_to_the_session(self):
        source = inspect.getsource(workspace_module.Workspace.start)
        assert "within_minutes=within_minutes," in source

    def test_the_whole_way_through(self, tmp_path, monkeypatch, quiet):
        """The one that would have caught this: a number posted to the
        API arriving on the session that runs the work."""
        seen = {}
        real = Session.__init__

        def spy(self, *a, **k):
            seen["minutes"] = k.get("within_minutes")
            real(self, *a, **k)

        monkeypatch.setattr(Session, "__init__", spy)
        work = workspace_module.Workspace()
        work.start(tmp_path, "a task", [], 0.0, within_minutes=35)
        assert seen["minutes"] == 35


class TestResumeCarriesItsOwn:
    def test_the_endpoint_takes_minutes(self):
        assert "minutes" in inspect.signature(web.resume).parameters

    def test_it_is_handed_on(self):
        assert "within_minutes=minutes" in inspect.getsource(web.resume)

    def test_resume_takes_it(self):
        assert "within_minutes" in inspect.signature(Session.resume).parameters

    def test_a_resumed_run_does_not_inherit_the_old_deadline(self):
        """The time it already spent is gone. Carrying the number forward
        would stop it in the same place every time it was resumed."""
        source = inspect.getsource(Session.resume)
        assert "within_minutes=within_minutes," in source
        assert "run.within_minutes" not in source


class TestTheCommandLineCarriesIt:
    def test_the_run_command_has_the_flag(self):
        source = inspect.getsource(cli.main)
        assert '"--minutes"' in source
        assert "end the run after this many minutes" in source

    def test_it_builds_a_should_stop_rather_than_hoping(self):
        source = inspect.getsource(cli._cmd_run)
        assert "should_stop=lambda: out_of_time[" in source

    def test_it_ends_the_workers_of_this_run_only(self):
        source = inspect.getsource(cli._cmd_run)
        assert "stop_workers(Path(run.repo))" in source

    def test_the_timer_is_cancelled_however_the_run_ends(self):
        source = inspect.getsource(cli._cmd_run)
        assert "finally:" in source
        assert "clock.cancel()" in source

    def test_no_flag_means_no_timer_and_no_stopping(self, monkeypatch, tmp_path):
        passed = {}

        def fake_execute(run, **k):
            passed.update(k)
            return run

        monkeypatch.setattr(cli, "execute", fake_execute)

        class Args:
            run = None
            items = None
            minutes = 0.0

        _a_run(tmp_path, monkeypatch)
        cli._cmd_run(Args())
        assert passed["should_stop"]() is False


class TestCancellation:
    def test_a_finished_run_owes_the_timer_nothing(self, tmp_path, monkeypatch):
        """A daemon timer that nobody cancels fires into a run that is
        over and stops whatever is running next."""
        source = inspect.getsource(Session._work)
        assert "finally:" in source
        assert "self._stop_the_clock()" in source

    def test_cancelling_twice_is_not_an_error(self, tmp_path):
        s = Session(tmp_path, "t", [], within_minutes=30)
        s.ends_in(30)
        s._stop_the_clock()
        s._stop_the_clock()
        assert s._clock is None

    def test_arming_twice_leaves_one_clock(self, tmp_path):
        s = Session(tmp_path, "t", [])
        s.ends_in(30)
        first = s._clock
        s.ends_in(30)
        assert s._clock is not first
        assert not first.is_alive() or first.finished.is_set()
        s._stop_the_clock()

    def test_it_really_fires_and_really_stops(self, tmp_path, monkeypatch):
        """End to end, in a second, with no model and no repository."""
        ended = {}
        monkeypatch.setattr(
            session_module,
            "stop_workers",
            lambda repo: ended.setdefault("repo", repo) and 0 or 1,
        )
        monkeypatch.setattr(Session, "_work", lambda self, auto_run: None)
        s = Session(tmp_path, "t", [], within_minutes=0.02)
        s.start()
        until = time.monotonic() + 5
        while not s.stopping and time.monotonic() < until:
            time.sleep(0.05)
        assert s.stopping, "the deadline did not stop the run"
        assert ended["repo"] == tmp_path, "it did not end this run's workers"


def _a_run(tmp_path, monkeypatch):
    """A run record with a plan, loaded from disk the way the CLI does."""
    from drydock.models import Item, Plan
    from drydock.run import Run

    monkeypatch.chdir(tmp_path)
    run = Run.start(tmp_path, "a task")
    run.plan = Plan(
        summary="one thing",
        items=[
            Item(id=1, title="t", rationale="r", files=["a.js"], verify_with="tests")
        ],
    )
    run.save()
    monkeypatch.setattr("drydock.run.Run.latest", classmethod(lambda cls: run))
    return run
