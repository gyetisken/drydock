"""Working out what somebody meant.

Typing a slash command before a sentence that plainly says what it wants is
a tax on using this. These are the sentences that have to route correctly,
and the ones that must not: the expensive path is never taken on a guess,
and nothing is reached by inference that could not be undone.
"""

from pathlib import Path

from drydock.intent import read


def to(text: str, repo: Path | None = None) -> str:
    return read(text, repo).command


class TestQuestions:
    def test_a_question_is_answered_not_acted_on(self):
        for said in (
            "which file decides whether an item is allowed to stay?",
            "what does the inspector check",
            "where is the test command defined",
            "why does the build fail on a fresh clone",
            "how does the memory work",
            "explain the four gates",
        ):
            assert to(said) == "/ask", said

    def test_an_instruction_wearing_a_question_mark_is_an_instruction(self):
        """'can you fix the header?' is not a question about the header."""
        assert to("can you fix the header spacing?") == "/fix"
        assert to("could you rename this function?") == "/fix"


class TestOneSmallChange:
    def test_a_single_change_skips_the_planning(self):
        for said in (
            "fix the typo in the footer",
            "rename validateEnquiry to checkEnquiry",
            "change the accent colour to green",
            "remove the unused import in server.js",
        ):
            assert to(said) == "/fix", said

    def test_several_changes_in_one_sentence_get_a_plan(self):
        """One sentence, three jobs. Planning it is what the plan is for."""
        said = "add a contact form, wire it to the validator, and write the tests"
        assert to(said) == "/do"

    def test_a_long_request_gets_a_plan(self):
        said = " ".join(["fix the thing that happens when"] + ["x"] * 40)
        assert to(said) == "/do"


class TestTheRest:
    def test_starting_something(self):
        assert to("build me a website for my bakery") == "/new"
        assert to("create a landing page for the launch") == "/new"

    def test_an_empty_folder_settles_it(self, tmp_path):
        """No mention of a website, but there is nothing here to change."""
        assert to("something for the shop round the corner", tmp_path) == "/new"

    def test_migrating_and_upgrading_are_different(self):
        assert to("migrate the test suite from JUnit 4 to JUnit 5") == "/migrate"
        assert to("upgrade express to 5") == "/upgrade"

    def test_looking_without_changing(self):
        assert to("audit this repository") == "/audit"
        assert to("what's fragile about this codebase") == "/audit"

    def test_running_what_is_already_there(self):
        assert to("run the tests") == "/check"
        assert to("build it") == "/check"


class TestItNeverGuessesExpensively:
    def test_an_unclear_change_is_planned_and_shown_first(self):
        guess = read("make the hours section show the whole week")
        assert guess.command == "/do"
        assert not guess.sure

    def test_a_named_command_always_wins(self):
        """However it reads, what somebody typed is what they meant."""
        assert to("/ask fix the typo in the footer") == "/ask"
        assert to("/new what does this do") == "/new"

    def test_every_guess_carries_its_reason(self):
        for said in ("what is this", "fix the footer", "build me a site"):
            assert read(said).why, said
