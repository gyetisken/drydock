"""Stop meant "finish everything already started, then stop".

The Corso B run is the case. A deadline of thirty-five minutes was set, a
stop was requested at 16:39:45 and accepted, and the run was still working
at 16:46. A worker was then killed outright at 16:44:36 - and a new one
started twenty-two seconds later, because a worker that is taken away is
read as "nothing was learned, try the same item again". Killing a worker
was a way of extending the run, not ending it. It took a person sending a
second stop and killing the workers twice to end it, at forty-two minutes.

The cause was in one line: `should_stop()` was consulted in exactly one
place, the top of the wave loop. Everything inside a wave - two attempts
of up to eighteen minutes, two revivals of twelve, the split that makes
new items, the two model opinions - ran without ever asking again. The
worst case after a stop request was close to an hour.

So it is asked wherever work is about to start, a worker taken away while
stopping is a result rather than a restart, and `stop(now=True)` ends the
workers of this run - in the repository and in every worktree it made.
"""

import inspect
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from drydock import engines, orchestrate
from drydock.models import Item, Outcome
from drydock.policy import of


def item(number: int = 1) -> Item:
    return Item(
        id=number,
        title=f"item {number}",
        rationale="because",
        files=["src/a.js"],
        verify_with="tests",
    )


class TestWhereItIsAsked:
    """Counted rather than described: every one of these is a place where
    work was started without asking."""

    def test_the_attempt_loop_asks_before_starting_one(self):
        source = inspect.getsource(orchestrate._one_item)
        before = source[: source.index("report, usage = work(")]
        assert "_stopping(should_stop)" in before

    def test_a_worker_taken_away_is_not_restarted_while_stopping(self):
        source = inspect.getsource(orchestrate._one_item)
        killed = source.index('if report.get("died")')
        assert "_stopping(should_stop)" in source[killed : killed + 400]
        # And the restart branch still exists for the ordinary case.
        assert "revived < REVIVALS" in source

    def test_the_two_opinions_are_not_spent_on_work_being_thrown_away(self):
        source = inspect.getsource(orchestrate._one_item)
        assert "elif _stopping(should_stop):" in source

    def test_an_item_is_not_split_while_stopping(self):
        source = inspect.getsource(orchestrate.execute)
        assert "not _stopping(should_stop) and _split_it(" in source

    def test_the_wave_loop_still_asks(self):
        assert "_stopping(should_stop)" in inspect.getsource(orchestrate.execute)

    def test_it_is_asked_in_more_than_one_place(self):
        """The whole fault was that it was asked once."""
        whole = Path("src/drydock/orchestrate.py").read_text()
        assert whole.count("_stopping(should_stop)") >= 5

    def test_the_callback_reaches_the_item(self):
        """It was never passed down, which is why it could not be asked."""
        assert "should_stop" in inspect.signature(orchestrate._one_item).parameters
        assert "should_stop" in inspect.signature(orchestrate._work_a_wave).parameters


class TestTheHelper:
    def test_no_callback_means_nothing_is_stopping(self):
        assert orchestrate._stopping(None) is False

    def test_a_callback_that_says_no(self):
        assert orchestrate._stopping(lambda: False) is False

    def test_a_callback_that_says_yes(self):
        assert orchestrate._stopping(lambda: True) is True

    def test_a_callback_that_throws_does_not_strand_the_run(self):
        """A broken stop button must not be a broken run."""

        def broken():
            raise RuntimeError("no")

        assert orchestrate._stopping(broken) is False


class TestStoppingEndsTheItem:
    """Behavioural, with a fake engineer: no model, no repository."""

    def _run_one(self, monkeypatch, tmp_path, stop_after_calls: int, died=False):
        calls = {"work": 0}

        def fake_work(*a, **k):
            calls["work"] += 1
            return (
                {
                    "done": True,
                    "summary": "",
                    "files_changed": [],
                    "noticed": [],
                    "question": "",
                    "died": died,
                },
                SimpleNamespace(
                    input_tokens=0,
                    output_tokens=0,
                    cached_tokens=0,
                    turns=1,
                    dollars=0.0,
                ),
            )

        monkeypatch.setattr(orchestrate, "work", fake_work)
        monkeypatch.setattr(
            orchestrate,
            "detect",
            lambda p: SimpleNamespace(
                build_command="npm run build", test_command="npm test", language="js"
            ),
        )

        here = SimpleNamespace(
            path=tmp_path,
            discard=lambda: calls.__setitem__("discarded", True),
            pending=lambda: "",
            sweep=list,
        )
        monkeypatch.setattr(orchestrate, "Repo", lambda p: here)

        asked = {"n": 0}

        def should_stop():
            asked["n"] += 1
            return asked["n"] > stop_after_calls

        run = SimpleNamespace(
            task="t",
            brief="t",
            as_briefed="t",
            handoff="",
            direction="",
            model="opus",
            skills_loaded=[],
            budget=0.0,
            left=0.0,
            id="20261119-000000",
            spend=lambda u: None,
            verification_baseline=SimpleNamespace(builds=True, tests_run=1),
            refused={},
        )
        result, _ = orchestrate._one_item(
            tmp_path,
            here,
            run,
            item(),
            "claude",
            "opus",
            of("balanced"),
            1.0,
            None,
            None,
            should_stop,
        )
        return result, calls

    def test_no_worker_is_started_when_already_stopping(self, monkeypatch, tmp_path):
        result, calls = self._run_one(monkeypatch, tmp_path, stop_after_calls=0)
        assert calls["work"] == 0, "a worker was started after stop"
        assert result.outcome is Outcome.BLOCKED
        assert "stopped" in result.note

    def test_the_tree_is_left_clean(self, monkeypatch, tmp_path):
        _result, calls = self._run_one(monkeypatch, tmp_path, stop_after_calls=0)
        assert calls.get("discarded"), "stopping must not leave an edit on disk"

    def test_a_killed_worker_is_not_restarted(self, monkeypatch, tmp_path):
        """The exact Corso B failure: kill, and it starts again."""
        result, calls = self._run_one(
            monkeypatch, tmp_path, stop_after_calls=1, died=True
        )
        assert calls["work"] == 1, "the killed worker was restarted"
        assert result.outcome is Outcome.BLOCKED
        assert "stopped while this was running" in result.note


class TestWhichWorkersAStopEnds:
    def test_the_repository_itself(self, tmp_path):
        assert engines._belongs_to(str(tmp_path), tmp_path)

    def test_a_worktree_this_run_made(self, tmp_path, monkeypatch):
        """Where the parallel items actually work. Matching only the
        repository path found none of them."""
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        tree = tmp_path / "home" / "worktrees" / f"{tmp_path.name}-item3"
        assert engines._belongs_to(str(tree), tmp_path)

    def test_not_another_project(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        other = tmp_path / "home" / "worktrees" / "somebodyelse-item1"
        assert not engines._belongs_to(str(other), tmp_path)
        assert not engines._belongs_to("/some/other/repo", tmp_path)

    def test_a_worker_with_no_home_named(self, tmp_path):
        assert not engines._belongs_to("", tmp_path)


class TestTheDeadline:
    """A timer, because the checkpoints are only reached between pieces of
    work: a worker with twelve minutes on its own clock would carry the run
    past the deadline and nothing would be asked until it finished."""

    def _session(self, tmp_path):
        from drydock.session import Session

        return Session(tmp_path, "a task", [])

    def test_no_deadline_by_default(self, tmp_path):
        assert self._session(tmp_path)._clock is None

    def test_zero_or_less_sets_nothing(self, tmp_path):
        s = self._session(tmp_path)
        s.ends_in(0)
        s.ends_in(-5)
        assert s._clock is None

    def test_it_arms_a_timer(self, tmp_path):
        s = self._session(tmp_path)
        s.ends_in(30)
        assert isinstance(s._clock, threading.Timer)
        assert s._clock.daemon, "a timer must not hold the process open"
        s._stop_the_clock()

    def test_it_fires_and_stops_the_run(self, tmp_path, monkeypatch):
        killed = {"n": 0}
        import drydock.session as session_module

        monkeypatch.setattr(
            session_module, "stop_workers", lambda repo: killed.__setitem__("n", 1) or 1
        )
        s = self._session(tmp_path)
        s.ends_in(0.02)  # a little over a second
        deadline = time.monotonic() + 5
        while not s.stopping and time.monotonic() < deadline:
            time.sleep(0.05)
        assert s.stopping, "the deadline did not stop the run"
        assert killed["n"] == 1, "the deadline did not end the workers"

    def test_cancelling_it_leaves_the_run_alone(self, tmp_path):
        s = self._session(tmp_path)
        s.ends_in(30)
        s._stop_the_clock()
        assert s._clock is None
        assert not s.stopping


class TestStopNow:
    def test_asking_does_not_kill(self, tmp_path, monkeypatch):
        import drydock.session as session_module

        called = {"n": 0}
        monkeypatch.setattr(
            session_module, "stop_workers", lambda repo: called.__setitem__("n", 1) or 1
        )
        s = TestTheDeadline()._session(tmp_path)
        s.stop()
        assert s.stopping
        assert called["n"] == 0, "the ordinary stop must leave the worker to finish"

    def test_telling_does(self, tmp_path, monkeypatch):
        import drydock.session as session_module

        called = {"repo": None}
        monkeypatch.setattr(
            session_module,
            "stop_workers",
            lambda repo: called.__setitem__("repo", repo) or 2,
        )
        s = TestTheDeadline()._session(tmp_path)
        s.stop(now=True)
        assert s.stopping
        assert called["repo"] == tmp_path


class TestNothingSafeWasLoosened:
    def test_an_item_stopped_mid_flight_is_still_discarded(self):
        source = inspect.getsource(orchestrate._one_item)
        for check in ("_stopping(should_stop)", "here.discard()"):
            assert check in source, check

    def test_the_wave_still_drops_its_worktrees(self):
        source = inspect.getsource(orchestrate._work_a_wave)
        assert "finally:" in source
        assert "repo.drop_worktree(where)" in source
        assert "_no_longer_serving(where)" in source

    def test_the_ordinary_revival_still_exists(self):
        """Stopping is the exception. A worker that dies on its own, with
        no stop requested, is still replaced - that was three items in one
        afternoon and the item was fine every time."""
        source = inspect.getsource(orchestrate._one_item)
        assert "revived < REVIVALS" in source
        assert "revived += 1" in source

    @pytest.mark.parametrize("profile", ["fast", "balanced", "deep"])
    def test_attempts_and_revivals_are_unchanged(self, profile):
        p = of(profile)
        assert p.attempts >= 2
        assert p.revivals == 2
