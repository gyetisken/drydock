"""What happens to the rest of a plan when one item fails.

The whole run used to stop. That was right when everything left needed the
item that failed and wrong the rest of the time, and the difference is
written down: every item names what it needs. What is pinned here is that
the run keeps what it can still do, and that it never attempts an item
against a foundation that is not there.
"""

from pathlib import Path

import pytest

from drydock import orchestrate
from drydock.models import Baseline, Check, Item, Plan
from drydock.run import Run


def an_item(number: int, needs=None, files=None) -> Item:
    return Item(
        id=number,
        title=f"item {number}",
        plain=f"thing {number}",
        rationale="because",
        files=files if files is not None else [f"src/{number}.js"],
        verify_with="tests",
        needs=needs or [],
    )


def a_run(tmp_path: Path, *items: Item) -> Run:
    run = Run(
        id="20261117-000000",
        repo=str(tmp_path),
        task="build it",
        started="2026-11-17T00:00:00",
    )
    run.baseline = Baseline(builds=True, tests_run=1, tests_failed=0, tests_skipped=0)
    run.plan = Plan(summary="A plan.", items=list(items))
    return run


class Crew:
    """The stations, with the engineer saying what it is told to say."""

    def __init__(self, monkeypatch, fails: set[int]):
        self.fails = fails
        self.attempted: list[int] = []

        monkeypatch.setattr(orchestrate, "work", self._work)
        monkeypatch.setattr(orchestrate, "Repo", _Quiet)
        monkeypatch.setattr(orchestrate, "detect", lambda path: _Chain())
        monkeypatch.setattr(orchestrate, "verify", lambda *a, **k: _Passed())
        monkeypatch.setattr(orchestrate, "look", lambda *a, **k: _Clean())
        monkeypatch.setattr(orchestrate, "_judge", lambda *a, **k: "")
        monkeypatch.setattr(orchestrate, "_work_a_wave", self._wave)

    def _wave(self, repo, repo_path, run, items, *a, **k):
        out = {}
        for item in items:
            result, _ = orchestrate._one_item(
                Path(run.repo),
                repo,
                run,
                item,
                "claude",
                "opus",
                False,
                0.0,
                None,
                None,
            )
            out[item.id] = result
        return out

    def _work(self, repo, task, item, build, failure="", *a, **k):
        self.attempted.append(item.id)
        if item.id in self.fails:
            return {"done": False, "summary": "could not", "files_changed": []}, None
        return (
            {"done": True, "summary": "did it", "files_changed": [], "question": ""},
            None,
        )


class _Chain:
    build_command = "npm run build"
    test_command = "npm test"


class _Passed:
    passed = True
    reason = "2 tests pass"
    check = Check(
        name="tests", command="npm test", passed=True, seconds=1.0, detail="2 pass"
    )


class _Clean:
    clean = True
    reason = "nothing to report"


class _Quiet:
    def __init__(self, path):
        self.path = path

    def pending(self):
        return "+++ b/x.js\n+1\n"

    def commit(self, message):
        return "abc1234"

    def discard(self):
        pass

    def sweep(self):
        pass

    def is_clean(self):
        return True

    def branch(self, name):
        pass

    def head(self):
        return "abc1234"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def outcomes(run) -> dict[int, str]:
    return {r.item.id: r.outcome.value for r in run.results}


class TestWhatStillGetsDone:
    def test_an_independent_item_is_still_attempted(self, here, monkeypatch):
        crew = Crew(monkeypatch, fails={1})
        run = a_run(here, an_item(1), an_item(2, needs=[1]), an_item(3))
        orchestrate.execute(run, engine="claude", model="opus", reviewing=False)

        assert 3 in crew.attempted
        assert outcomes(run)[3] == "done"

    def test_an_item_that_needed_it_is_never_attempted(self, here, monkeypatch):
        """Running it against a foundation that is not there wastes an
        engineer and produces a failure that means nothing."""
        crew = Crew(monkeypatch, fails={1})
        run = a_run(here, an_item(1), an_item(2, needs=[1]), an_item(3))
        orchestrate.execute(run, engine="claude", model="opus", reviewing=False)

        assert 2 not in crew.attempted
        assert outcomes(run)[2] == "blocked"

    def test_it_says_what_the_stranded_item_was_waiting_on(self, here, monkeypatch):
        Crew(monkeypatch, fails={1})
        run = a_run(here, an_item(1), an_item(2, needs=[1]))
        orchestrate.execute(run, engine="claude", model="opus", reviewing=False)

        note = next(r.note for r in run.results if r.item.id == 2)
        assert "needs item 1" in note
        assert "still there to do" in note

    def test_every_item_in_the_plan_ends_with_a_result(self, here, monkeypatch):
        """A plan item with no result at all is the one thing a run must
        not leave behind: it reads as never planned."""
        Crew(monkeypatch, fails={2})
        run = a_run(
            here, an_item(1), an_item(2), an_item(3, needs=[2]), an_item(4, needs=[1])
        )
        orchestrate.execute(run, engine="claude", model="opus", reviewing=False)

        assert set(outcomes(run)) == {1, 2, 3, 4}
        assert outcomes(run)[4] == "done"

    def test_nothing_failing_changes_nothing(self, here, monkeypatch):
        crew = Crew(monkeypatch, fails=set())
        run = a_run(here, an_item(1), an_item(2, needs=[1]), an_item(3))
        orchestrate.execute(run, engine="claude", model="opus", reviewing=False)

        assert sorted(crew.attempted) == [1, 2, 3]
        assert set(outcomes(run).values()) == {"done"}
