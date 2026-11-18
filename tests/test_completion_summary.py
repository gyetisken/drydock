"""What the window is told when a run finishes.

A run used to end on one line: "1 of 1 items landed", a test count, a
branch name and a preview link. Everything else it knew - which commit,
which files, which command was actually run and what it said, which
planned items are not in the branch at all - was in the record and shown
to nobody. A reader could not tell a verified landing from a hopeful one.

Two of those lines were worse than thin. The branch was rebuilt in the
browser out of the session key with the `-resumed` suffix trimmed by
hand, a guess at a string that is written down; and the cost was called
"$2.24 of work" on an engine where nothing is billed per run and no cap
was enforced.

So: everything shown here comes off the record, and a field nobody filled
in says so rather than defaulting to something cheerful.
"""

import ast
from pathlib import Path

import pytest

from drydock.models import Check, Item, ItemResult, Outcome, Plan
from drydock.run import Run

HERE = Path(__file__).resolve().parents[1] / "src" / "drydock"
CHAT = (HERE / "static" / "chat.js").read_text()
SESSION = (HERE / "session.py").read_text()


def an_item(id: int, plain: str = "") -> Item:
    return Item(
        id=id,
        title=f"item {id}",
        plain=plain,
        rationale="because",
        files=["a.py"],
        verify_with="tests",
    )


def a_landing(id: int, **kw) -> ItemResult:
    fields = {
        "item": an_item(id, "the health check answers"),
        "outcome": Outcome.DONE,
        "files_changed": ["server.js", "server.test.js"],
        "checks": [Check(name="tests", command="npm test", passed=True, seconds=1.2)],
        "commit": "6e2e0f9cfd1122",
        "verified_commit": "6e2e0f9cfd1122",
        "note": "1 tests pass",
    }
    return ItemResult(**(fields | kw))


def a_run(tmp_path: Path, items: list[Item], results: list[ItemResult]) -> Run:
    run = Run.start(tmp_path, "build something")
    run.plan = Plan(summary="a plan", items=items)
    run.results = results
    return run


class TestVerifiedSuccess:
    def test_the_branch_comes_off_the_record(self, tmp_path):
        """Not rebuilt from the session key. `run.branch` is the one true
        answer, and a resumed run is exactly the case where guessing it
        from the key went wrong."""
        run = a_run(tmp_path, [an_item(1)], [a_landing(1)])
        assert run.what_happened()["branch"] == run.branch

    def test_each_landing_carries_its_commit_files_and_checks(self, tmp_path):
        run = a_run(tmp_path, [an_item(1)], [a_landing(1)])
        (landed,) = run.what_happened()["landed"]

        assert landed["commit"] == "6e2e0f9cfd"
        assert landed["verified"] is True
        assert landed["files"] == ["server.js", "server.test.js"]
        assert landed["checks"] == [
            {"name": "tests", "command": "npm test", "passed": True}
        ]

    def test_a_landing_nobody_verified_says_so(self, tmp_path):
        """`commit` is where a worker put it; `verified_commit` is where
        it was found afterwards on the integrated branch. Only the second
        is evidence, so the difference has to be visible."""
        run = a_run(tmp_path, [an_item(1)], [a_landing(1, verified_commit=None)])
        (landed,) = run.what_happened()["landed"]

        assert landed["verified"] is False
        assert landed["commit"] == "6e2e0f9cfd"


class TestPartiallyLanded:
    def test_an_item_that_was_refused_is_named_with_its_reason(self, tmp_path):
        run = a_run(
            tmp_path,
            [an_item(1), an_item(2)],
            [
                a_landing(1),
                ItemResult(
                    item=an_item(2, "the contact form posts"),
                    outcome=Outcome.REVERTED,
                    attempts=2,
                    note="the tests failed twice and were rolled back",
                ),
            ],
        )
        said = run.what_happened()

        assert len(said["landed"]) == 1
        (missed,) = said["missed"]
        assert missed["plain"] == "the contact form posts"
        assert missed["outcome"] == "reverted"
        assert "rolled back" in missed["note"]
        assert missed["attempts"] == 2

    def test_an_item_the_run_never_reached_is_still_listed(self, tmp_path):
        """A run that stops early leaves items with no result at all. Left
        out of the summary they read as items that were never planned,
        which is the quiet version of claiming the plan was finished."""
        run = a_run(
            tmp_path, [an_item(1), an_item(2, "the search page")], [a_landing(1)]
        )
        said = run.what_happened()

        (missed,) = said["missed"]
        assert missed["plain"] == "the search page"
        assert missed["outcome"] == "never attempted"
        assert said["planned"] == 2

    def test_a_tree_that_failed_integration_is_carried(self, tmp_path):
        run = a_run(tmp_path, [an_item(1)], [a_landing(1)])
        run.integration_error = "two commits are missing from the branch"
        assert run.what_happened()["integration_error"] == (
            "two commits are missing from the branch"
        )


class TestMetadataNobodyRecorded:
    def test_a_landing_with_no_checks_claims_nothing(self, tmp_path):
        """An empty `checks` list is not a pass. It is the absence of a
        judgement, and the window has to say that word."""
        run = a_run(tmp_path, [an_item(1)], [a_landing(1, checks=[])])
        (landed,) = run.what_happened()["landed"]

        assert landed["checks"] == []
        assert "no checks recorded" in CHAT

    def test_a_landing_with_no_commit_is_none_not_a_blank_sha(self, tmp_path):
        run = a_run(
            tmp_path, [an_item(1)], [a_landing(1, commit=None, verified_commit=None)]
        )
        (landed,) = run.what_happened()["landed"]

        assert landed["commit"] is None
        assert "commit not recorded" in CHAT

    def test_a_landing_with_no_files_is_shown_as_unrecorded(self, tmp_path):
        run = a_run(tmp_path, [an_item(1)], [a_landing(1, files_changed=[])])
        (landed,) = run.what_happened()["landed"]

        assert landed["files"] == []
        assert "files not recorded" in CHAT

    def test_an_item_with_no_plain_sentence_falls_back_to_its_title(self, tmp_path):
        run = a_run(tmp_path, [an_item(1)], [a_landing(1, item=an_item(1, plain=""))])
        (landed,) = run.what_happened()["landed"]
        assert landed["plain"] == "item 1"

    def test_a_run_with_no_plan_says_nothing_rather_than_breaking(self, tmp_path):
        """The read-only path and the crash path both emit a summary, and
        neither is guaranteed a plan."""
        run = Run.start(tmp_path, "look at this repository")
        said = run.what_happened()

        assert said["landed"] == [] and said["missed"] == []
        assert said["planned"] == 0


class TestWhatTheCostMeans:
    def test_an_unenforced_spend_is_not_called_a_budget(self, tmp_path):
        """The engine most runs use bills nothing per run. "$2.24 of work"
        on a subscription is a number with no claim behind it, and AGENTS.md
        asks for an enforced limit to be distinguished from an observed
        one."""
        run = a_run(tmp_path, [an_item(1)], [a_landing(1)])
        run.dollars = 2.2449

        said = run.what_happened()
        assert said["cost"] == 2.24
        assert said["cost_is_enforced"] is False
        assert 'cost_is_enforced ? "of a capped budget" : "observed"' in CHAT

    def test_a_real_cap_is_reported_as_one(self, tmp_path):
        run = a_run(tmp_path, [an_item(1)], [a_landing(1)])
        run.budget = 3.0
        assert run.what_happened()["cost_is_enforced"] is True


class TestTheWindowIsGivenAllOfIt:
    """The payload is only useful if every summary carries it, and a
    duplicated keyword here is a `TypeError` at the end of a finished run -
    the most expensive possible moment to raise one."""

    def summaries(self) -> list[ast.Call]:
        found = []
        for node in ast.walk(ast.parse(SESSION)):
            if not isinstance(node, ast.Call):
                continue
            args = node.args
            if (
                args
                and isinstance(args[0], ast.Constant)
                and args[0].value == "run.summary"
            ):
                found.append(node)
        return found

    def test_every_summary_spreads_the_record(self):
        calls = self.summaries()
        assert len(calls) == 3, "a new summary emitter needs the record too"
        for call in calls:
            spread = [k for k in call.keywords if k.arg is None]
            assert spread, "this summary does not carry run.what_happened()"
            (star,) = spread
            assert isinstance(star.value, ast.Call)
            assert star.value.func.attr == "what_happened"

    def test_no_summary_passes_a_field_the_record_already_carries(self, tmp_path):
        """`cost=` alongside the spread record is "got multiple values for
        keyword argument 'cost'", raised after all the work is done."""
        from_record = set(Run.start(tmp_path, "build something").what_happened())
        for call in self.summaries():
            named = {k.arg for k in call.keywords if k.arg}
            assert not (named & from_record), sorted(named & from_record)


class TestTheWindowShowsIt:
    """The browser code is read as source here, the way the other UI tests
    in this project do it. It is not proof that it renders; it is proof
    that the values shown are the ones off the record and that the
    not-recorded wording exists to be shown."""

    @pytest.mark.parametrize(
        "shown",
        [
            "it.commit",
            "it.files",
            "it.checks",
            "it.attempts",
            "e.branch",
            "e.integration_error",
        ],
    )
    def test_the_summary_reads_the_recorded_field(self, shown):
        assert shown in CHAT

    def test_the_branch_is_no_longer_rebuilt_from_the_session_key(self):
        assert "drydock/${esc((S.key" not in CHAT
        assert "${esc(e.branch" in CHAT

    def test_items_that_did_not_land_are_rendered(self):
        assert "function whatDidNot(" in CHAT
        assert "Not in the branch" in CHAT

    def test_a_missing_remote_is_still_reported_by_the_server(self):
        """Unchanged, and tested here so it stays that way: the window asks
        whether it can publish and prints the refusal, rather than offering
        a pull request a repository with no remote cannot have."""
        assert "/api/can-publish/" in CHAT
        assert "The work is on its" in CHAT
