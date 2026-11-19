"""When a judgement may be overruled, and when it may not.

One run ended at five items of twelve. The twelfth was refused twice by
the critic - "the footer is not on the page at either width" - and six
items that needed it were never attempted. The code built, the suite
grew, the inspector found nothing, and the reviewer said the diff did the
item. The only thing wrong with it was how it looked, and that threw away
half a run.

The four gates are not worth the same and this program says so
everywhere: measured, then checked, then seen. So on the last attempt the
weakest of the four stops being a veto and becomes what it always was -
something true that somebody should know. It is kept with the item,
reported, and read back by `/qa`.

Only the critic, only alone, and only on the last attempt.
"""

import inspect

import pytest

from drydock import orchestrate
from drydock.models import ItemResult

SOURCE = inspect.getsource(orchestrate._one_item)
DECISION = SOURCE[
    SOURCE.index('outstanding = ""') : SOURCE.index(
        "if verdict.passed and not refusal:"
    )
]


class TestWhenItIsOverruled:
    def test_only_when_the_critic_was_alone(self):
        assert 'refused_by == ["critic"]' in DECISION

    def test_only_on_the_last_attempt(self):
        assert "attempt >= policy.attempts" in DECISION

    def test_only_when_everything_measurable_passed(self):
        assert "verdict.passed" in DECISION

    def test_the_objection_is_kept_rather_than_dropped(self):
        assert 'outstanding, refusal = refusal, ""' in DECISION

    def test_it_is_said_out_loud_when_it_happens(self):
        assert "on_event" in DECISION
        assert "kept, with what I said against it" in DECISION


class TestWhatIsNeverOverruled:
    def test_the_inspector_keeps_its_veto(self):
        """It counts removed tests, weakened assertions and committed
        credentials. Arithmetic does not get overruled by anything."""
        refusing = SOURCE[SOURCE.index("report_card.clean") :]
        assert 'refused_by = ["inspector"]' in refusing
        assert '"inspector"' not in DECISION.replace("critic", "")

    def test_the_reviewer_is_not_in_the_exception(self):
        """It read the item against the diff, which is a stronger claim
        than a picture."""
        assert "reviewer" not in DECISION

    def test_two_refusals_together_are_not_overruled(self):
        """`== ["critic"]` and not `"critic" in ...`: if the reviewer
        refused as well, the item goes back."""
        assert 'refused_by == ["critic"]' in DECISION
        assert '"critic" in refused_by' not in DECISION

    def test_a_failing_suite_is_not_overruled(self):
        assert "verdict.passed" in DECISION


class TestItIsWrittenDown:
    def test_the_result_carries_it(self):
        one = ItemResult.model_fields["outstanding"]
        assert one.default == ""

    def test_the_note_says_it_was_kept_anyway(self):
        assert "Kept with this against it" in SOURCE

    def test_it_is_handed_on_with_the_item(self):
        assert "outstanding=outstanding," in SOURCE

    @pytest.mark.parametrize("field", ["outstanding"])
    def test_an_older_record_without_it_still_reads(self, field, tmp_path):
        """Runs saved before this existed have no such field, and the
        history is read back on every page load."""
        from drydock.models import Item, Outcome

        one = ItemResult(
            item=Item(id=1, title="t", rationale="r", files=[], verify_with="tests"),
            outcome=Outcome.DONE,
        )
        assert getattr(one, field) == ""


class TestItReachesSomebody:
    """Written down and not shown is the same as not written down."""

    def test_the_summary_carries_it(self):
        import inspect

        from drydock.run import Run

        assert '"outstanding": result.outstanding,' in inspect.getsource(
            Run.what_happened
        )

    def test_the_window_draws_it(self):
        from pathlib import Path

        chat = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "drydock"
            / "static"
            / "chat.js"
        ).read_text()

        assert "kept, with this against it" in chat
        assert "it.outstanding" in chat

    def test_a_clean_item_says_nothing(self):
        from pathlib import Path

        chat = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "drydock"
            / "static"
            / "chat.js"
        ).read_text()
        drawn = chat[chat.index("it.outstanding") :]

        assert drawn.startswith("it.outstanding ?"), (
            "it has to be conditional, or every item carries the line"
        )


class TestApprovingARunThatWasStopped:
    """A plan can arrive after somebody asked the run to stop: the worker
    writing it does not stop mid-sentence. Approving one then started
    work on a run whose worktrees were being taken away underneath it,
    and came back as `IndexError: list index out of range`.
    """

    def test_it_is_refused_and_says_why(self):
        import inspect

        from drydock import web

        source = inspect.getsource(web.approve)
        assert "session.stopping" in source
        assert "this run was stopped" in source

    def test_the_refusal_comes_before_the_work(self):
        import inspect

        from drydock import web

        source = inspect.getsource(web.approve)
        assert source.index("session.stopping") < source.index("session.approve()")


class TestAskingGitForSomethingItHasNot:
    def test_a_repository_with_no_commits_has_no_head(self, tmp_path):
        """`splitlines()[0]` was an IndexError the moment git said
        nothing, and reading the output without its exit code returned
        "fatal: Needed a single revision" as though it were a hash."""
        import subprocess

        from drydock.repo import Repo

        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

        said = Repo(tmp_path).head()

        assert said == ""
        assert "fatal" not in said

    def test_a_repository_with_one_still_has_one(self, tmp_path):
        import subprocess

        from drydock.repo import Repo

        for args in (
            ["init", "-q"],
            ["config", "user.email", "t@t"],
            ["config", "user.name", "t"],
            ["commit", "-q", "--allow-empty", "-m", "x"],
        ):
            subprocess.run(["git", "-C", str(tmp_path), *args], check=True)

        assert len(Repo(tmp_path).head()) >= 7
