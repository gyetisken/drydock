"""The prompt told the engineer two different things about running tests.

The engineer's own instructions said "Do not verify your own work, and do
not prove it", and the engine added "turns spent demonstrating that your
change works are turns taken from making it work". The greenfield skill,
appended underneath both, said "make it fail before making it pass" -
which is a test run, by definition, and then a second one.

Measured on the successful LUMI run: `npm test` at 17:15:51, 17:15:59 and
17:16:01. Three runs of the whole suite in ten seconds. The cost in time
was nine seconds and is not the point; a prompt that contradicts itself
makes every decision under it more expensive than it needs to be.

So the two are separated rather than one of them deleted. Running
something to find out is part of building and is encouraged: compile as
you go, run the test you just wrote, run the few that cover what you just
changed. Running the whole suite afterwards to show it passes is the
verifier's job and happens whether the engineer does it or not.

The same run wrote eighteen tests for a page of markup. Nothing asked for
eighteen and nothing capped it either - what was missing was any sense of
proportion, so the rule is what could plausibly be wrong: money,
concurrency, sessions and parsed input earn their edge cases; markup and
styling earn a few checks on what must appear and what must not be
invented.

And two pieces of guidance had gone stale. The engineer was told to prefer
`replace_in_file` over `write_file` - tools that exist only on the API
path, which nothing can reach any more. It has `Edit` and `Write`.
"""

from pathlib import Path

from drydock import engineer
from drydock.skills import briefing, discover, load

SKILL = Path("skills/greenfield/SKILL.md").read_text()


def flat(text: str) -> str:
    return " ".join(text.split())


SYSTEM = flat(engineer.SYSTEM)
PROMPT = flat(engineer.PROMPT)


def verify_section() -> str:
    """What the skill says to whoever checks the work.

    `briefing(..., "engineer")` returns only the Engineer section, so an
    assertion about the Verify section has to read the file.
    """
    at = SKILL.index("## Verify")
    return flat(SKILL[at : SKILL.index("## Checked against", at)])


def guidance() -> str:
    here = Path("skills").resolve()
    sk = [load(s) for s in discover(here) if s.name == "greenfield"]
    assert sk, "the greenfield skill should be discoverable"
    return flat(briefing(sk, "engineer"))


class TestFindingOutIsNotProving:
    def test_the_two_are_named_apart(self):
        assert "Run things to find out, not to prove" in SYSTEM

    def test_finding_out_is_encouraged(self):
        assert "Finding out is part of building and you should do it freely" in SYSTEM
        assert "run the one test you just wrote" in SYSTEM
        assert "run the handful that cover the thing you just changed" in SYSTEM

    def test_only_the_full_suite_as_a_demonstration_is_refused(self):
        assert "Running the full suite yourself afterwards to show that it" in SYSTEM

    def test_it_says_who_does_the_proving(self):
        assert "its whole suite is run by something that is not you" in SYSTEM

    def test_repeating_a_run_for_reassurance_is_the_thing_to_stop(self):
        assert "running it again for reassurance is the thing to stop doing" in SYSTEM

    def test_the_skill_no_longer_asks_for_the_suite(self):
        said = guidance()
        assert "write it before the code it covers" in said
        assert "run that one test and watch it fail" in said
        assert "That is the one test, not the suite" in said

    def test_the_skill_says_who_runs_the_suite(self):
        assert "is done for you either way" in guidance()

    def test_the_point_of_a_failing_test_is_kept(self):
        """Not deleted - a test that has never failed has not been shown
        to test anything."""
        assert "one that has never failed has not been shown to test" in guidance()

    def test_the_engine_still_says_the_suite_is_run_for_them(self):
        # The sentence is split across two string literals in the
        # source, so the join has to come out before it reads as one.
        source = flat(Path("src/drydock/engines.py").read_text()).replace('" "', "")
        assert "the suite is run for you afterwards" in source

    def test_nothing_says_not_to_compile(self):
        assert "compile as you go" in SYSTEM
        assert SYSTEM.count("compile as you go") == 1


class TestDepthFollowsTheWork:
    def test_the_rule_is_what_could_plausibly_be_wrong(self):
        assert "Test what could plausibly be wrong" in SYSTEM
        assert "nothing for the sake of a number" in SYSTEM

    def test_the_risky_kinds_are_named(self):
        for kind in (
            "money",
            "concurrency",
            "authentication",
            "permissions",
            "retries",
            "anything that writes to a store",
            "anything that parses input from outside",
        ):
            assert kind in SYSTEM, kind

    def test_their_edge_cases_are_the_point(self):
        assert "the edge cases are the point" in SYSTEM
        assert "the second identical request" in SYSTEM
        assert "a suite that covers only the happy path has tested nothing" in SYSTEM

    def test_markup_and_styling_earn_a_few_checks(self):
        assert "Markup, styling and content cannot be wrong in that way" in SYSTEM
        assert "A handful of checks on what the page must actually contain" in SYSTEM

    def test_it_says_what_not_to_assert_on_a_page(self):
        assert "Asserting the presence of every heading" in SYSTEM
        assert "the value of a padding" in SYSTEM
        assert "fails whenever somebody improves the page" in SYSTEM

    def test_there_is_no_count_anywhere(self):
        """Not a cap. A number would be the same mistake in the other
        direction."""
        import re

        for said in (SYSTEM, guidance()):
            block = said[said.find("Test what could plausibly") :][:1400]
            assert not re.search(
                r"\b(at least|at most|no more than)\s+\w+ tests", block
            )

    def test_the_skill_says_the_bar_is_not_a_number(self):
        said = verify_section()
        assert "The bar is not a number" in said
        assert "Judge it by what could plausibly break" in said

    def test_the_skill_still_refuses_an_empty_suite(self):
        said = verify_section()
        assert "a suite that passes because it contains nothing" in said
        assert "It should only ever go up" in said

    def test_what_was_left_untested_is_reported(self):
        assert "say in the report what you decided was not worth testing" in (
            verify_section()
        )


class TestASimpleStaticSite:
    """A page of markup and styling. The LUMI run wrote eighteen."""

    def test_the_engineer_is_told_a_handful_is_the_whole_of_it(self):
        said = SYSTEM[SYSTEM.index("Markup, styling and content") :][:600]
        assert "is the whole of it" in said
        assert "Write the few that would catch a real mistake and stop" in said

    def test_it_is_still_told_what_those_few_must_cover(self):
        said = SYSTEM[SYSTEM.index("Markup, styling and content") :][:600]
        assert "the facts that have to appear" in said
        assert "the ones that must not be invented" in said
        assert "the thing the request fixed" in said

    def test_the_visual_check_is_untouched(self):
        looking = flat(engineer.LOOKING)
        assert "drydock-look" in looking
        assert "the pictures are the only way you actually see" in looking
        assert "This is not a check that counts" in looking


class TestABackendTask:
    def test_rigour_is_required_rather_than_merely_allowed(self):
        said = SYSTEM[SYSTEM.index("Test what could plausibly") :][:900]
        assert "needs tests, and needs them to be real" in said

    def test_the_cases_that_break_quietly_are_named(self):
        said = SYSTEM[SYSTEM.index("Test what could plausibly") :][:900]
        for case in ("the empty list", "the expired key", "the two callers at once"):
            assert case in said, case

    def test_nothing_exempts_them(self):
        """The proportionality rule must not read as permission to skip
        tests on anything that matters."""
        assert "cannot be wrong in that way" in SYSTEM
        at = SYSTEM.index("Markup, styling and content")
        assert SYSTEM.index("Behaviour that can be wrong") < at


class TestTheInstructionsNameRealThings:
    def test_the_dead_tools_are_gone(self):
        for name in ("replace_in_file", "write_file"):
            assert name not in SYSTEM, name

    def test_the_tools_it_actually_has_are_named(self):
        assert "The text you give Edit has to match the file exactly" in SYSTEM
        assert "Write replaces a whole file and hides that" in SYSTEM

    def test_those_are_the_tools_it_is_given(self):
        source = Path("src/drydock/engines.py").read_text()
        assert '"Read Edit Write Glob Grep "' in source

    def test_the_narrow_edit_advice_survived_the_rename(self):
        assert "Prefer narrow edits" in SYSTEM
        assert "right for a file you are creating" in SYSTEM

    def test_the_end_of_the_item_no_longer_contradicts_the_heading(self):
        """ "Run things to find out" and "finishing is not a phase for
        finding out" were two paragraphs apart and said opposite things
        about the same words."""
        assert "Finishing is not a phase for finding out" not in SYSTEM
        assert "At the end, you already know what you know" in SYSTEM

    def test_the_three_wasted_calls_are_still_named(self):
        said = SYSTEM[SYSTEM.index("At the end, you already know") :][:700]
        assert "searching the source for a tag you wrote yourself" in said
        assert "checking the same file's syntax twice" in said


class TestNothingImportantWasCompressedAway:
    def test_the_scope_rule(self):
        assert "The item you are given is the entire scope" in SYSTEM
        assert "If you find a real problem outside the item" in SYSTEM

    def test_the_autonomy(self):
        assert "inside it, the implementation is yours" in SYSTEM
        assert '"It did not say" is not a reason for the obvious version' in SYSTEM

    def test_the_brief_still_wins(self):
        assert "The brief at the top is what the finished thing is judged" in SYSTEM

    def test_the_verification_is_still_untouchable(self):
        assert "Do not touch the verification" in SYSTEM
        assert "loosening an assertion" in SYSTEM

    def test_asking_once_survives(self):
        assert "Ask rather than guess, once" in SYSTEM

    def test_finishing_means_reporting(self):
        assert "Finishing means writing the report" in SYSTEM
        assert "never reported is an item that is thrown away" in SYSTEM

    def test_whole_before_better_survives(self):
        assert "**Whole first, then better.**" in PROMPT

    def test_the_handoff_is_still_there(self):
        assert "{known}" in engineer.PROMPT
        assert "{criteria}" in engineer.PROMPT


class TestNothingDownstreamChanged:
    def test_the_gates_still_run(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "verdict = verify(" in source
        assert "report_card = look(" in source
        assert "if verdict.passed and unverified:" in source

    def test_stop_deadline_rollback_and_checkpoint(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert source.count("_stopping(should_stop)") >= 5
        assert "here.discard()" in source
        assert source.count("here.checkpoint(") >= 2
        from drydock.session import Session

        assert Session(Path("/tmp"), "t", [], within_minutes=20).within_minutes == 20

    def test_no_limit_was_imposed(self):
        from drydock.policy import BALANCED, PROFILES

        assert PROFILES[BALANCED].turns == 60
        assert PROFILES[BALANCED].minutes == 12.0
        assert PROFILES[BALANCED].self_looks == 3
