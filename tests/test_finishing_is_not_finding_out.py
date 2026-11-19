"""The engineer finished the work and then went looking for what it knew.

Corso C, the last eighty-two seconds of an item that was already done.
Its final edit landed at +363s. What it did between +394s and +468s,
read out of its own session:

    Read  .drydock-look/desktop.png      a 267KB picture of the page
    Bash  curl ... | grep -c "<svg"      refused: curl is not allowed
    Grep  <svg                           searching for a tag it wrote
    Grep  svg                            the same question again
    Read  .drydock-look/phone.png        a 97KB picture of the page
    Bash  node --check test/corso.test.js
    Bash  node --check <the same file, absolute path>
    Read  test/corso.test.js
    Read  public/styles.css offset=170
    Write .drydock-report.json

Four of those established nothing: the refused curl, two greps for a tag
it had written itself and could see in the picture it had just opened,
and a syntax check repeated on the file it had just syntax-checked. Nine
seconds of commands, and rather more of deciding to run them.

The rest was the work: the two pictures are visual refinement, the first
`node --check` is compiling as you go, the two reads are so the report
says what is actually there, and the report is the thing that makes the
item exist at all. None of that is discouraged here and all of it is
pinned below.

The existing rule in the prompt - "do not verify your own work" - is
about running the suite, which is not what happened. What happened is
re-deriving a fact already in hand, and that is now named, with the three
shapes it took.
"""

from drydock import engineer, engines, look
from drydock.policy import of


def flat(text: str) -> str:
    return " ".join(text.split())


SYSTEM = flat(engineer.SYSTEM)


class TestTheFinishingPhaseIsNamed:
    def test_it_says_finishing_is_not_for_finding_out(self):
        assert "Finishing is not a phase for finding out" in SYSTEM

    def test_it_names_searching_the_source_for_your_own_work(self):
        assert "searching the source for a tag you wrote yourself" in SYSTEM

    def test_it_names_asking_the_page_what_the_picture_shows(self):
        assert (
            "asking the running page a question the picture in front of you "
            "already answers" in SYSTEM
        )

    def test_it_names_checking_the_same_file_twice(self):
        assert "checking the same file's syntax twice" in SYSTEM

    def test_it_is_concrete_rather_than_another_principle(self):
        """The abstract version was already there and was not followed."""
        assert "did all three" in SYSTEM
        assert "learned nothing it did not have before it started" in SYSTEM


class TestWhatIsStillEncouraged:
    """The expensive half of that block was the work. If this change
    stops any of it, it has made the engineer worse, not faster."""

    def test_reading_the_page_it_changed(self):
        assert "reading the page you changed" in SYSTEM

    def test_reading_its_own_files_for_an_honest_report(self):
        assert (
            "reading your own files so the report says what is actually there" in SYSTEM
        )

    def test_compiling_as_it_goes(self):
        assert "compiling as you go" in SYSTEM
        assert "Compile as you go" in engineer.SYSTEM
        assert "Compile while you work" in engineer.SYSTEM

    def test_they_are_marked_as_worth_the_turns(self):
        assert "are worth the turns" in SYSTEM
        assert "Keep doing those" in SYSTEM

    def test_looking_at_the_page_is_still_offered(self):
        assert "drydock-look" in engineer.LOOKING
        assert "Open every picture it names with Read" in flat(engineer.LOOKING)


class TestItIsAlsoSaidWhereItHappens:
    """The system prompt is read once, six minutes before the moment. The
    look's own output is read at it."""

    def test_the_look_says_it_too(self):
        said = flat(look.NOT_A_CHECK)
        assert "you do not need to go and confirm again in the source" in said

    def test_it_offers_the_two_ways_out(self):
        said = flat(look.NOT_A_CHECK)
        assert "Change what needs changing, or finish and report" in said

    def test_the_look_still_says_it_is_not_a_gate(self):
        said = flat(look.NOT_A_CHECK)
        assert "not a check that counts" in said
        assert "somebody who is not you" in said


class TestNothingWasTakenAway:
    """This is a prompt change. A tool removed would be a different
    change with different risks, and the engineer needs all of them."""

    def test_the_engineers_tools_are_unchanged(self):
        rule = engines._shell_rule("npm run build")
        assert rule == "Bash(npm *)"

    def test_the_file_tools_are_unchanged(self):
        source = engines.ClaudeCodeEngine.work.__doc__ or ""
        assert source is not None
        from pathlib import Path

        text = Path("src/drydock/engines.py").read_text()
        assert '"Read Edit Write Glob Grep "' in text

    def test_grep_is_still_available(self):
        from pathlib import Path

        text = Path("src/drydock/engines.py").read_text()
        assert "Grep" in text, "the greps were wasteful here, not forbidden"

    def test_the_look_budget_did_not_move(self):
        assert of("balanced").self_looks == 3
        assert of("fast").self_looks == 2

    def test_the_turn_and_minute_budget_did_not_move(self):
        p = of("balanced")
        assert (p.turns, p.minutes, p.attempts) == (60, 12.0, 2)


class TestTheGatesAreUntouched:
    def test_the_scope_rule_still_stands(self):
        assert "The item you are given is the entire scope" in engineer.SYSTEM

    def test_the_verification_rule_still_stands(self):
        assert "Do not touch the verification" in engineer.SYSTEM

    def test_the_old_rule_about_the_suite_is_still_there(self):
        """This adds to it; it does not replace it."""
        assert "Do not verify your own work, and do not prove it" in engineer.SYSTEM

    def test_the_report_is_still_the_last_thing(self):
        assert "Finishing means writing the report" in engineer.SYSTEM

    def test_the_brief_still_outranks_the_item(self):
        assert "what the finished thing is judged against" in SYSTEM
