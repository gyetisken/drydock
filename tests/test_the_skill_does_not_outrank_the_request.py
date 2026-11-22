"""The skill was telling the planner to do what the rules forbid.

The second LUMI run went from five items to one and dropped the
timezone module, which was the planning rules working. What the run's
own command line showed is that it worked *against* the skill appended
below it: `greenfield` said "the first item is the skeleton that proves
the loop works", "compose the page out of pieces that different items
can own" and "one feature per item" - three instructions to split work
that the rules above had just said not to split.

And the timezone module was not invented out of nothing either. The
skill carried a worked example of a restaurant site with a live
open-or-closed line, with the words "The live line is worth having". A
request that said "a website for an Italian restaurant" and nothing
else met that paragraph, and the first run planned a daylight-saving
module with its own suite.

Underneath both: `briefing()` ranked a skill above everything except
the repository, which puts a document written months ago for nobody in
particular above the sentence somebody typed this morning.

What was worth keeping was kept - tests with the code, the ignore file
before the install, "answer the question the visitor came with", the
whole design-currency block - and the splitting is left to the rules
that already decide it.
"""

from pathlib import Path

from drydock.skills import briefing, discover, load

SKILL = Path("skills/greenfield/SKILL.md").read_text()
FLAT = " ".join(SKILL.split())


def greenfield():
    here = Path("skills").resolve()
    return [load(s) for s in discover(here) if s.name == "greenfield"]


class TestTheContradictionsAreGone:
    def test_no_skeleton_first_item(self):
        assert "skeleton that proves the loop works" not in FLAT
        assert "The first item is the skeleton" not in FLAT

    def test_no_one_feature_per_item(self):
        assert "one feature per item" not in FLAT

    def test_no_instruction_to_split_a_page_into_items(self):
        assert "pieces that different items can own" not in FLAT
        assert "items that own separate files are worked on at the same time" not in (
            FLAT
        )

    def test_the_restaurant_hours_example_is_gone(self):
        for said in (
            "Closed now. Opens next on Tuesday",
            "The live line is worth having",
            "eleven at night",
        ):
            assert said not in FLAT, said

    def test_nothing_in_it_biases_a_site_towards_a_clock(self):
        for word in ("timezone", "daylight", "DST", "open now", "opening hours"):
            assert word.lower() not in FLAT.lower(), word

    def test_the_duplicated_paragraph_is_gone(self):
        """It said the same sentence twice, two paragraphs apart."""
        assert FLAT.count("each with its test in the same item") <= 1


class TestWhatWasWorthKeepingWasKept:
    def test_tests_arrive_with_the_code(self):
        assert "Tests arrive with the code that they test, in the same item" in FLAT
        assert "nothing to test against and no way back" in FLAT

    def test_the_ignore_file_before_the_install(self):
        assert "The .gitignore belongs in the first item, before anything is" in FLAT
        assert "it has to exist before the install, not after" in FLAT

    def test_answer_the_question_the_visitor_came_with(self):
        assert "Every page exists for somebody with a question" in FLAT
        assert '"3 unread" does not replace the list' in FLAT

    def test_that_rule_is_not_read_as_a_licence_to_add_machinery(self):
        """It is about not removing what somebody came for. The first
        run read it as a reason to compute something."""
        assert "It is not a licence to add machinery" in FLAT
        assert "the plainest page that answers the question is the answer" in FLAT

    def test_the_order_and_the_leave_it_till_last_rules(self):
        assert "Order by what other things depend on" in FLAT
        assert "Leave deployment, packaging and documentation to the end" in FLAT

    def test_the_engineer_guidance_is_untouched(self):
        assert "Never improvise an asset" in FLAT
        assert "Do not invent requirements" in FLAT
        # Reworded so it asks for the one test rather than the suite:
        # the engineer's own instructions forbid running the suite to
        # prove anything. See test_what_is_worth_testing.
        assert "run that one test and watch it fail" in FLAT

    def test_the_verification_bar_is_untouched(self):
        assert "a suite that passes because it contains nothing" in FLAT
        assert "It should only ever go up" in FLAT

    def test_the_design_currency_block_is_untouched(self):
        assert "Checked against what is current" in FLAT
        assert "text-wrap: balance" in FLAT
        assert "oklch()" in FLAT

    def test_it_now_defers_on_how_work_is_cut_up(self):
        assert "How the work is cut up is not this skill's to decide" in FLAT
        assert "they outrank anything here" in FLAT


class TestTheRankingIsSaidOutLoud:
    def said(self) -> str:
        return " ".join(briefing(greenfield(), "plan").split())

    def test_there_is_a_skill_to_test_with(self):
        assert greenfield(), "the greenfield skill should be discoverable"

    def test_the_request_is_first_and_is_never_overridden(self):
        said = self.said()
        assert "What the person asked for comes first and is never overridden" in said

    def test_the_rules_come_before_the_skill(self):
        said = self.said()
        assert "Then the instructions above this block" in said
        assert "This block is last" in said

    def test_the_repository_still_beats_a_generalisation(self):
        said = self.said()
        assert "a fact about this job where a skill is a generalisation" in said

    def test_a_skill_may_not_add_a_feature_nobody_asked_for(self):
        said = self.said()
        assert (
            "may not add an item, a feature or a requirement that the person "
            "did not ask for" in said
        )

    def test_a_skill_may_not_redecide_the_split(self):
        said = self.said()
        assert "may not change how the work is cut up" in said

    def test_a_disagreement_is_reported_rather_than_silently_resolved(self):
        said = self.said()
        assert "say in your answer that the two disagreed" in said

    def test_the_ranking_comes_before_the_skill_text_itself(self):
        said = self.said()
        assert said.index("This block is last") < said.index("From the skill")

    def test_no_skills_means_no_preamble(self):
        assert briefing([], "plan") == ""
