"""Verifying the tree everything landed in, not just each item alone.

Items in a wave are worked in separate worktrees and each is verified
there, on its own. They are then cherry-picked home one at a time. A
cherry-pick that applies cleanly means no two items touched the same
lines; it does not mean the result works.

So two items could each pass, land cleanly, and leave a repository whose
suite fails - and both were reported as done, the branch was pushed and a
pull request was opened saying every item had passed its checks.
"""

from pathlib import Path

import pytest

from drydock import orchestrate
from drydock.models import Baseline, Check, Item, ItemResult, Outcome, Plan
from drydock.policy import of
from drydock.run import Run


def an_item(number: int, **kw) -> Item:
    return Item(
        **{
            "id": number,
            "title": f"item {number}",
            "plain": f"thing {number}",
            "rationale": "because",
            "files": [f"src/{number}.js"],
            "verify_with": "tests",
            "needs": [],
            **kw,
        }
    )


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job = Run(
        id="20261118-000000",
        repo=str(tmp_path),
        task="two items at once",
        started="2026-11-18T00:00:00",
    )
    job.baseline = Baseline(builds=True, tests_run=3, tests_failed=0, tests_skipped=0)
    job.plan = Plan(summary="Two.", items=[an_item(1), an_item(2)])
    return job


class Tree:
    """A repository that remembers what was asked of it."""

    def __init__(self):
        self.at = "base0000"
        self.taken: list[str] = []
        self.undone: list[str] = []

    def __call__(self, path):
        self.path = path
        return self

    def worktree(self, name, at):
        return Path(f"/tmp/worktree-{name}")

    def drop_worktree(self, where):
        pass

    def take(self, commit):
        self.taken.append(commit)
        self.at = f"landed{len(self.taken)}"
        return True, self.at

    def rewind(self, commit):
        self.undone.append(commit)
        self.at = commit
        return True, ""

    def head(self):
        return self.at

    def is_clean(self):
        return True

    def sweep(self):
        pass


def passing(item, commit) -> tuple:
    return (
        ItemResult(
            item=item,
            outcome=Outcome.DONE,
            note="4 tests pass",
            checks=[
                Check(
                    name="tests",
                    command="npm test",
                    passed=True,
                    seconds=1.0,
                    detail="4 pass",
                )
            ],
        ),
        commit,
    )


class _Passed:
    passed = True
    reason = "4 tests pass"
    tests_run = 4
    check = Check(
        name="tests", command="npm test", passed=True, seconds=1.0, detail="4 pass"
    )


class _Failed:
    passed = False
    reason = "2 tests failing"
    tests_run = 4
    check = Check(
        name="tests", command="npm test", passed=False, seconds=1.0, detail="2 failed"
    )


def two_items_land(monkeypatch, run, tree, integrated):
    """Both items pass alone and cherry-pick cleanly; the tree they make
    together verifies as `integrated` says."""
    monkeypatch.setattr(orchestrate, "Repo", tree)
    monkeypatch.setattr(orchestrate, "detect", lambda path: _Chain())
    monkeypatch.setattr(
        orchestrate,
        "_one_item",
        lambda where, main, job, item, *a, **k: passing(item, f"item{item.id}"),
    )
    monkeypatch.setattr(orchestrate, "verify", lambda *a, **k: integrated)
    return orchestrate._work_a_wave(
        tree,
        Path(run.repo),
        run,
        run.plan.items,
        "claude",
        "opus",
        of(None),
        0.0,
        None,
        None,
    )


class _Chain:
    build_command = "npm run build"
    test_command = "npm test"


class TestTheTreeEverythingLandedIn:
    def test_a_wave_that_works_together_is_reported_as_done(self, run, monkeypatch):
        tree = Tree()
        out = two_items_land(monkeypatch, run, tree, _Passed())

        assert [r.outcome for r in out.values()] == [Outcome.DONE, Outcome.DONE]
        assert tree.undone == []

    def test_a_wave_that_breaks_together_is_not_reported_as_done(
        self, run, monkeypatch
    ):
        """Each item passed in its own worktree and both cherry-picks
        applied. The suite still fails in the tree they made together,
        and nothing about that is visible from either item alone."""
        tree = Tree()
        out = two_items_land(monkeypatch, run, tree, _Failed())

        assert all(r.outcome is not Outcome.DONE for r in out.values())

    def test_the_commits_are_taken_back_out(self, run, monkeypatch):
        tree = Tree()
        two_items_land(monkeypatch, run, tree, _Failed())

        assert tree.undone, "the branch was left carrying work that does not work"

    def test_what_landed_before_this_wave_is_left_alone(self, run, monkeypatch):
        """Earlier rounds were verified in the tree they made at the time,
        so they are known good. The branch goes back to where it stood
        when this round began - not further."""
        tree = Tree()
        tree.at = "earlier9"
        two_items_land(monkeypatch, run, tree, _Failed())

        assert tree.undone == ["earlier9"], "it went back exactly one round"
        assert tree.at == "earlier9", "and stopped there"

    def test_the_failure_says_what_it_was(self, run, monkeypatch):
        tree = Tree()
        out = two_items_land(monkeypatch, run, tree, _Failed())

        notes = " ".join(r.note for r in out.values())
        assert "together" in notes or "2 tests failing" in notes


class TestNothingIsPublishedThatDidNotPass:
    """A branch that fails its own suite must not be pushed with a pull
    request saying every item passed its checks."""

    def test_a_reverted_wave_counts_as_nothing_landed(self, run, monkeypatch):
        tree = Tree()
        out = two_items_land(monkeypatch, run, tree, _Failed())
        landed = sum(1 for r in out.values() if r.outcome is Outcome.DONE)
        assert landed == 0

    def test_publishing_needs_something_that_landed(self):
        """`_publish` returns before touching the network when nothing
        did, and a reverted wave is nothing."""
        import inspect

        from drydock.session import Session

        source = inspect.getsource(Session._publish)
        assert "if not landed" in source
        assert source.index("if not landed") < source.index("signed_in")

    def test_the_body_never_lists_a_reverted_item_as_landed(self, tmp_path):
        """Already true, and worth keeping true: the evidence only ever
        comes from results that say done."""
        import inspect

        from drydock import publish

        source = inspect.getsource(publish.evidence_from)
        assert 'outcome.value != "done"' in source
