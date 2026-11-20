"""Acceptance criteria that were written and shown to nobody.

The paytest run. The planner wrote an item whose `plain` field held three
thousand characters of "what must be true afterwards", including:

    "Different payload" is judged on the fields the service actually acts
    on (amount, currency, reference), so JSON key order or a field the
    service ignores must not produce a 409

The engineer fingerprinted the whole request body, so a field the service
ignores did produce a 409. The reviewer approved. An independent audit
afterwards found it.

Neither station failed. `reviewer.PROMPT` and `engineer.PROMPT` were both
built from `title` + `rationale`, and the criteria live in `plain` - 3131
characters that reached nobody. Worse, the `rationale` both of them did
see said the opposite:

    everything else - module boundaries, naming, fingerprint mechanism -
    is left to the person with the code open

So the item contradicted itself and only the permissive half travelled.
The engineer built what it was told it could build; the reviewer approved
what it was given.

Both now get the criteria, both are told the brief outranks them, and
neither is allowed to resolve a contradiction quietly: the engineer asks,
the reviewer reports.
"""

import inspect

from drydock import engineer, reviewer
from drydock.models import Item


def flat(text: str) -> str:
    return " ".join(text.split())


def an_item(**kw) -> Item:
    return Item(
        **{
            "id": 1,
            "title": "idempotent POST /payments",
            "plain": "A repeat with the same key returns the first payment.",
            "rationale": "because retries happen",
            "files": ["server.js"],
            "verify_with": "tests",
            **kw,
        }
    )


class TestTheEngineerGetsThem:
    def test_the_prompt_has_a_place_for_them(self):
        assert "{criteria}" in engineer.PROMPT

    def test_they_are_labelled_as_what_must_be_true(self):
        said = flat(engineer.PROMPT)
        assert "What has to be true when this item is done" in said
        assert "acceptance criteria the plan was approved on" in said

    def test_it_is_told_something_else_will_read_the_change_against_them(self):
        assert "something that is not you will read the change against them" in flat(
            engineer.PROMPT
        )

    def test_they_are_built_from_plain(self):
        source = inspect.getsource(engineer.work)
        assert "criteria=(item.plain" in source

    def test_an_item_with_none_says_so_rather_than_showing_a_blank(self):
        built = engineer.PROMPT.format(
            repo="r",
            build_command="npm test",
            shell="s",
            task="t",
            id=1,
            title="t",
            rationale="r",
            files="a.js",
            verify_with="tests",
            criteria="  (the plan recorded none for this item)",
        )
        assert "(the plan recorded none for this item)" in built


class TestTheReviewerGetsThem:
    def test_the_prompt_has_a_place_for_them(self):
        assert "{criteria}" in reviewer.PROMPT

    def test_checking_them_is_named_as_its_first_question(self):
        assert "the first of your three questions" in flat(reviewer.PROMPT)

    def test_a_criterion_the_change_does_not_meet_is_a_rejection(self):
        """Not a note. This is the one that was missed."""
        assert "including a criterion above that the change does not meet" in flat(
            reviewer.PROMPT
        )

    def test_they_are_built_from_plain(self):
        source = inspect.getsource(reviewer)
        assert "criteria=(item.plain" in source

    def test_they_come_before_the_diff(self):
        said = flat(reviewer.PROMPT)
        assert said.index("{criteria}") < said.index("{diff}")


class TestTheBriefStillOutranksThem:
    def test_the_engineer_is_told_the_order(self):
        said = flat(engineer.PROMPT)
        assert "The brief at the top wins over everything" in said

    def test_a_criterion_outranks_the_reasoning_but_not_the_brief(self):
        said = flat(engineer.PROMPT)
        assert "worth more than the item's reasoning" in said

    def test_the_engineer_builds_the_brief_when_they_disagree(self):
        said = flat(engineer.PROMPT)
        assert (
            "If a criterion contradicts the brief, build what the brief asked for "
            "and say so in your report" in said
        )

    def test_the_reviewer_judges_against_the_brief_when_they_disagree(self):
        said = flat(reviewer.PROMPT)
        assert "judge the change against what the person asked for" in said

    def test_the_brief_is_still_in_both_prompts(self):
        assert "{task}" in engineer.PROMPT
        assert "what the finished thing is judged against" in flat(engineer.PROMPT)


class TestAContradictionIsSurfacedRatherThanResolved:
    def test_the_engineer_does_not_pick_one(self):
        said = flat(engineer.PROMPT)
        assert "What you must not do is pick one quietly" in said

    def test_the_engineer_asks_instead(self):
        said = flat(engineer.PROMPT)
        assert "that is not yours to resolve: put it in `question`" in said
        assert "change nothing" in said

    def test_the_reviewer_does_not_pick_one(self):
        said = flat(reviewer.PROMPT)
        assert "Do not quietly pick one and review against it" in said

    def test_the_reviewer_reports_it_as_a_fault_in_the_plan(self):
        said = flat(reviewer.PROMPT)
        assert "a fault in the plan rather than in this change" in said
        assert "put it in `noticed`, say which two disagree and how" in said

    def test_a_plan_fault_is_not_charged_to_the_engineer(self):
        """The paytest contradiction was the planner's. Refusing the item
        for it would have spent an attempt on work nobody could fix."""
        said = flat(reviewer.PROMPT)
        assert said.index("fault in the plan") < said.index("Do not quietly pick one")


class TestNothingElseInThosePromptsMoved:
    def test_the_engineer_still_has_one_item_of_scope(self):
        assert "The item you are given is the entire scope" in engineer.SYSTEM

    def test_the_reviewer_still_asks_its_three_questions(self):
        said = flat(reviewer.SYSTEM)
        assert "Does this diff achieve what the item said?" in said
        assert "Does it change behaviour the item never mentioned?" in said
        assert "weakening what was being checked" in said

    def test_the_reviewer_still_ignores_the_size_of_the_change(self):
        assert "How much changed is not one of the questions" in flat(reviewer.SYSTEM)

    def test_the_authorised_files_are_still_passed(self):
        assert "{files}" in reviewer.PROMPT
        assert "files=" in inspect.getsource(reviewer)

    def test_the_item_shape_is_unchanged(self):
        it = an_item()
        assert it.plain and it.rationale and it.files
