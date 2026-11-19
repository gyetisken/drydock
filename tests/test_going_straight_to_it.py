"""Whether anybody is stopped to look before the work starts.

Every change that did not match a pattern went down the path that writes
a plan and waits for approval, because the sentence was all the router
had to go on. So "change the heading colour to blue" could cost a survey,
a plan, and somebody reading four items before a word moved.

The job reads the repository before it plans now, and the thing that read
it is the only thing here that knows what the change actually touches. So
it answers the question as well: is this worth stopping for.

Three things insist on being shown, and none can be argued out of it: a
floor raised under risky work, a plan of more than one item, and the
worker saying so itself.
"""

import inspect
from pathlib import Path

import pytest

from drydock import start
from drydock.session import Session

SESSION = inspect.getsource(Session)


class TestTheQuestionIsAsked:
    def test_the_worker_is_asked_whether_to_stop(self):
        fields = start._tool().schema["properties"]
        assert "needs_a_plan" in fields
        assert "why_that" in fields
        assert "needs_a_plan" in start._tool().schema["required"]

    def test_it_is_asked_about_what_was_found_not_what_was_typed(self):
        said = start._tool().schema["properties"]["needs_a_plan"]["description"]
        assert "read the repository" in said
        assert "wording of the request" in said

    def test_a_missing_answer_means_show_it(self):
        """The question is "may this skip being shown". Silence is not a
        yes."""
        assert start._said({"summary": "s", "items": []}).needs_a_plan is True

    @pytest.mark.parametrize("given,wanted", [(True, True), (False, False)])
    def test_the_answer_is_carried(self, given, wanted):
        said = start._said(
            {"summary": "s", "items": [], "needs_a_plan": given, "why_that": "w"}
        )
        assert said.needs_a_plan is wanted
        assert said.why_that == "w"


class TestWhatInsistsOnBeingShown:
    def source(self) -> str:
        # To the bracket that closes it, not to the first one in it - the
        # first is inside `len(...)`, and slicing there reads half the
        # condition and passes anyway.
        at = SESSION.index("straight = (")
        return SESSION[at : SESSION.index("\n        )", at)]

    def test_a_raised_floor_cannot_be_skipped(self):
        """Migrations, who is allowed in, money, removing data. The whole
        point of a floor is that it is not negotiable."""
        assert "not self.floor" in self.source()

    def test_more_than_one_item_cannot_be_skipped(self):
        assert "len(started.plan.items) <= 1" in self.source()

    def test_the_worker_saying_so_cannot_be_skipped(self):
        assert "not started.needs_a_plan" in self.source()

    def test_skipping_is_said_out_loud(self):
        assert '"plan.skipped"' in SESSION
        chat = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "drydock"
            / "static"
            / "chat.js"
        ).read_text()
        assert '"plan.skipped"' in chat
        assert "Going straight to it" in chat

    def test_what_is_still_true_is_said_with_it(self):
        """Nobody approved it, so the thing that makes that safe has to be
        on screen: it is still a commit and it still has to pass."""
        chat = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "drydock"
            / "static"
            / "chat.js"
        ).read_text()
        skipped = chat[chat.index('"plan.skipped"') :]
        skipped = skipped[: skipped.index("},")]
        assert "its own commit" in skipped
        assert "pass the checks" in skipped


class TestTheRouterStoppedGuessingAtSize:
    def test_the_default_no_longer_promises_a_plan(self):
        from drydock.intent import read

        guess = read("rework how the sidebar collapses")

        assert guess.command == "/do"
        assert "shown to you before anything happens" not in guess.why
        assert "reading the repository" in guess.why
