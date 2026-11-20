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
        self._serial_wave = orchestrate._work_a_wave

        monkeypatch.setattr(orchestrate, "work", self._work)
        monkeypatch.setattr(orchestrate, "Repo", _Quiet)
        monkeypatch.setattr(orchestrate, "detect", lambda path: _Chain())
        monkeypatch.setattr(orchestrate, "verify", lambda *a, **k: _Passed())
        monkeypatch.setattr(orchestrate, "look", lambda *a, **k: _Clean())
        # Nothing refused it, nobody refused it, and nothing went
        # unverified: `_judge` reports all three. A refusal from the critic
        # alone on the last attempt is not worth the same as one from the
        # inspector, and a check that could not finish is neither.
        monkeypatch.setattr(orchestrate, "_judge", lambda *a, **k: ("", [], [], []))
        monkeypatch.setattr(orchestrate, "_work_a_wave", self._wave)
        # Splitting a failed item asks the planner, which is a model call.
        # These tests are about what happens to the rest of the plan, so
        # the planner says the item is one thing and the run carries on as
        # it did before splitting existed.
        monkeypatch.setattr(orchestrate, "split", lambda *a, **k: ([], None))

    def _wave(self, repo, repo_path, run, items, *a, **k):
        out = {}
        for item in items:
            out.update(self._serial_wave(repo, repo_path, run, [item], *a, **k))
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
    has_tests = True


class _Passed:
    """A verdict that passed, carrying the count the suite reported."""

    passed = True
    reason = "the tests pass"
    check = Check(
        name="tests", command="npm test", passed=True, seconds=1.0, detail="pass"
    )

    def __init__(self, tests_run: int = 2):
        self.tests_run = tests_run
        self.checks = [self.check]


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

    def start_history(self):
        pass

    def sweep(self):
        pass

    def is_clean(self):
        return True

    def branch(self, name):
        pass

    def head(self):
        return "abc1234"

    def branch_exists(self, name):
        return False

    def require_checkout(self, branch, tip=None):
        return tip or "previous"

    def require_parent(self, candidate, previous):
        pass


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
        orchestrate.execute(run, engine="claude", model="opus", policy=no_diff_review())

        assert 3 in crew.attempted
        assert outcomes(run)[3] == "done"

    def test_an_item_that_needed_it_is_never_attempted(self, here, monkeypatch):
        """Running it against a foundation that is not there wastes an
        engineer and produces a failure that means nothing."""
        crew = Crew(monkeypatch, fails={1})
        run = a_run(here, an_item(1), an_item(2, needs=[1]), an_item(3))
        orchestrate.execute(run, engine="claude", model="opus", policy=no_diff_review())

        assert 2 not in crew.attempted
        assert outcomes(run)[2] == "blocked"

    def test_it_says_what_the_stranded_item_was_waiting_on(self, here, monkeypatch):
        Crew(monkeypatch, fails={1})
        run = a_run(here, an_item(1), an_item(2, needs=[1]))
        orchestrate.execute(run, engine="claude", model="opus", policy=no_diff_review())

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
        orchestrate.execute(run, engine="claude", model="opus", policy=no_diff_review())

        assert set(outcomes(run)) == {1, 2, 3, 4}
        assert outcomes(run)[4] == "done"

    def test_nothing_failing_changes_nothing(self, here, monkeypatch):
        crew = Crew(monkeypatch, fails=set())
        run = a_run(here, an_item(1), an_item(2, needs=[1]), an_item(3))
        orchestrate.execute(run, engine="claude", model="opus", policy=no_diff_review())

        assert sorted(crew.attempted) == [1, 2, 3]
        assert set(outcomes(run).values()) == {"done"}


class TestTheBarMovesUpWithTheWork:
    """The count to beat was taken before the run started and never moved.
    An item could delete every test an earlier item in the same run had
    added and still clear it, as long as it stayed at the number the
    repository began with - while the pull request said, in those words,
    that every item left the suite at least as large as it found it."""

    def test_a_landed_item_raises_the_bar(self, here, monkeypatch):
        crew = Crew(monkeypatch, fails=set())
        monkeypatch.setattr(orchestrate, "verify", lambda *a, **k: _Passed(11))
        run = a_run(here, an_item(1))
        run.baseline.tests_run = 3
        orchestrate.execute(run, engine="claude", model="opus", policy=no_diff_review())

        assert run.baseline.tests_run == 3
        assert run.verification_baseline.tests_run == 11
        assert crew.attempted == [1]

    def test_a_later_item_is_measured_against_it(self, here, monkeypatch):
        """Item two deleting item one's tests is the case this exists for."""
        counts = iter([11, 11, 3, 3])
        required = []

        def report(_path, _mode, base, _commands):
            required.append(base.tests_run)
            return _Passed(next(counts))

        Crew(monkeypatch, fails=set())
        monkeypatch.setattr(orchestrate, "verify", report)
        run = a_run(here, an_item(1), an_item(2, needs=[1]))
        run.baseline.tests_run = 3

        orchestrate.execute(run, engine="claude", model="opus", policy=no_diff_review())
        # The second item was measured against eleven, not three. What the
        # verifier does with that is its own test; what matters here is
        # that the number it was given had moved.
        assert required == [3, 3, 11, 11]
        assert run.verification_baseline.tests_run == 11

    def test_a_smaller_count_never_lowers_the_bar(self, here, monkeypatch):
        """An item verified by its build reports no tests at all. That is
        not a reason to let the next one lose some."""
        counts = iter([_Passed(11), _Passed(11), _Passed(0), _Passed(0)])
        Crew(monkeypatch, fails=set())
        monkeypatch.setattr(orchestrate, "verify", lambda *a, **k: next(counts))
        run = a_run(here, an_item(1), an_item(2, needs=[1]))
        run.baseline.tests_run = 3

        orchestrate.execute(run, engine="claude", model="opus", policy=no_diff_review())
        assert run.verification_baseline.tests_run == 11


class TestWhichItemsAreLookedAt:
    """A critic sent to judge a placeholder page refuses it for being a
    placeholder. That is true and useless, and three attempts went on an
    item that had been finished the first time."""

    def test_the_planner_decides_when_it_has_said(self):
        from drydock.models import Item

        scaffolding = Item(
            id=1,
            title="the project runs and has a test command",
            rationale="first",
            files=["package.json"],
            verify_with="tests",
            worth_looking_at=False,
        )
        assert scaffolding.worth_looking_at is False

    def test_saying_nothing_leaves_it_to_the_diff(self):
        """Older plans, and any item the planner skipped the question on."""
        from drydock.models import Item

        item = Item(id=1, title="t", rationale="r", files=[], verify_with="tests")
        assert item.worth_looking_at is None

    def test_the_diff_still_knows_a_page_when_it_sees_one(self):
        from drydock.orchestrate import _changes_the_view

        assert _changes_the_view("+++ b/src/pages/index.astro\n+<h1>x</h1>\n")
        assert _changes_the_view("+++ b/app/globals.css\n+body{}\n")
        assert not _changes_the_view("+++ b/src/hours/week.js\n+export const x=1\n")

    def test_it_survives_the_run_being_written_down(self):
        from drydock.models import Item, Plan

        plan = Plan(
            summary="s",
            items=[
                Item(
                    id=1,
                    title="t",
                    rationale="r",
                    files=[],
                    verify_with="tests",
                    worth_looking_at=False,
                )
            ],
        )
        back = Plan.model_validate_json(plan.model_dump_json())
        assert back.items[0].worth_looking_at is False


def no_diff_review():
    """The default policy with the reviewer off, which is what these tests
    stood on before policies existed."""
    from drydock.policy import as_told, of

    return as_told(of(None), read_the_diff=False)


def reading():
    """The default policy, unchanged."""
    from drydock.policy import of

    return of(None)
