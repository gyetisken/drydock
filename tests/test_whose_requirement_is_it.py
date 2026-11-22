"""A reading the planner invented was enforced as though it was asked for.

The paytest run. The brief said only that reusing a key with a different
payload must return 409. The planner wrote this into the item's criteria:

    "Different payload" is judged on the fields the service actually acts
    on (amount, currency, reference), so JSON key order or a field the
    service ignores must not produce a 409

That is a defensible reading of an ambiguous sentence, and it is also
narrower than what most services do - nobody asked for it. Downstream it
carried exactly the weight of "$85 for a tune-up", which the person did
ask for, because nothing told the engineer or the reviewer which was
which.

The second run showed the other end of it. The planner wrote "(see
direction)" into an item on a backend job, where the designer had
correctly been skipped and the direction was zero characters long - a
pointer to a document the engineer was never given.

So: a plan says which of its criteria came from the person and which it
settled itself, an item may not refer to a direction that does not
exist, and the two groups are worth different amounts downstream. The
one the person asked for holds. The one the planner decided is a
starting point the engineer may depart from with a reason, and the
reviewer does not refuse work for crossing a line nobody drew.
"""

from drydock import engineer, planner, reviewer, start
from drydock.planner import PLAN_SCHEMA


def flat(text: str) -> str:
    return " ".join(text.split())


PLAIN = PLAN_SCHEMA["properties"]["items"]["items"]["properties"]["plain"][
    "description"
]


class TestNoPointerToADirectionThatIsNotThere:
    def test_the_worker_is_told_not_to_refer_to_one(self):
        said = flat(start.UNSEEN)
        assert "do not refer to one" in said

    def test_the_case_is_named(self):
        said = flat(start.UNSEEN)
        assert '"(see direction)" when no direction existed' in said

    def test_it_says_what_to_do_instead(self):
        assert "If a thing matters, the item says it" in flat(start.UNSEEN)

    def test_the_schema_says_the_same(self):
        field = start._tool().schema["properties"]["direction"]["description"]
        assert "nothing in the plan may refer to it" in flat(field)

    def test_the_schema_no_longer_asks_for_a_stylesheet(self):
        """Left over from before the designer stopped dictating values:
        the prompt was changed and the schema was not."""
        field = flat(start._tool().schema["properties"]["direction"]["description"])
        assert "palette as hex values" not in field
        assert "type scale" in field  # named as the engineer's, not asked for
        assert "the hex, the type scale and the spacing are the engineer's" in field

    def test_an_empty_direction_is_still_allowed(self):
        """Backend work has no direction and that is correct."""
        field = start._tool().schema["properties"]["direction"]["description"]
        assert "Empty when nobody looks at the result" in flat(field)


class TestThePlanSaysWhoseRequirementItIs:
    def test_both_planning_paths_carry_the_rule(self):
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert "Say which of it is theirs and which of it is yours" in said

    def test_the_two_headings_are_named(self):
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM), flat(PLAIN)):
            assert "From what was asked" in said
            assert "Decided here" in said

    def test_the_cost_of_not_separating_them_is_stated(self):
        said = flat(start.SYSTEM)
        assert "a reading you invented is enforced exactly as hard as a price" in said

    def test_a_decided_criterion_is_not_a_requirement(self):
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM), flat(PLAIN)):
            assert "not a requirement" in said

    def test_nothing_downstream_refuses_for_departing_from_one(self):
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert "nothing downstream refuses work for departing from it" in said

    def test_an_empty_second_group_is_an_answer(self):
        """Inventing an assumption to look thorough is the failure."""
        said = flat(start.SYSTEM)
        assert "If there is nothing in the second group, say so" in said
        assert "inventing one to look thorough" in said


class TestThePlainFieldSaysWhatItIsFor:
    def test_it_is_no_longer_described_as_one_short_sentence(self):
        """It is handed to the engineer and the reviewer as the criteria
        the work is held to. A planner obeying "under 80 characters"
        would have sent them one sentence labelled as the whole of it."""
        assert "Under 80 characters" not in PLAIN
        assert "one short sentence" not in PLAIN

    def test_it_names_both_of_its_readers(self):
        said = flat(PLAIN)
        assert "the person deciding whether to let the work happen" in said
        assert "the engineer and the reviewer" in said

    def test_it_is_still_readable_by_somebody_who_will_not_open_the_files(self):
        """The approval screen is still one of its two jobs."""
        said = flat(PLAIN)
        assert "no paths, no symbol names, no jargon" in said

    def test_it_is_still_outcome_rather_than_implementation(self):
        assert "says the outcome and nothing about how to reach it" in flat(PLAIN)


class TestDownstreamTellsThemApart:
    def test_the_engineer_knows_which_holds(self):
        said = flat(engineer.PROMPT)
        assert '"From what was asked" is the person\'s requirement and holds' in said

    def test_the_engineer_may_depart_from_a_decided_one(self):
        said = flat(engineer.PROMPT)
        assert "you may do it differently when the code in front of you says" in said
        assert "Say which one you departed from and why" in said

    def test_the_reviewer_rejects_for_a_missed_requirement(self):
        said = flat(reviewer.PROMPT)
        assert "a change that does not meet it is a rejection" in said

    def test_the_reviewer_does_not_reject_for_a_departed_decision(self):
        said = flat(reviewer.PROMPT)
        assert "departing from it is not a fault" in said
        assert "Refusing work for crossing a line nobody drew" in said


class TestTheBriefStillOutranksEverything:
    def test_the_engineer_is_told_so(self):
        assert "The brief at the top wins over everything" in flat(engineer.PROMPT)

    def test_a_criterion_that_contradicts_the_brief_loses(self):
        said = flat(engineer.PROMPT)
        assert (
            "If a criterion contradicts the brief, build what the brief asked for"
            in said
        )

    def test_the_reviewer_judges_against_the_brief(self):
        assert "judge the change against what the person asked for" in flat(
            reviewer.PROMPT
        )

    def test_a_contradiction_is_still_surfaced_rather_than_resolved(self):
        assert "What you must not do is pick one quietly" in flat(engineer.PROMPT)
        assert "Do not quietly pick one and review against it" in flat(reviewer.PROMPT)


class TestNothingAboutPlanningShapeMoved:
    def test_one_item_is_still_an_answer(self):
        from drydock.policy import of

        assert of("balanced").fewest_items == 1
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert "One item is a real answer" in said

    def test_the_two_wasteful_item_kinds_are_still_refused(self):
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert "implementation detail of another item" in said
            assert "checking item" in said

    def test_the_implementation_is_still_the_engineers(self):
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert "the engineer" in said

    def test_the_schema_still_carries_every_field_the_gates_use(self):
        item = PLAN_SCHEMA["properties"]["items"]["items"]["properties"]
        for field in ("plain", "rationale", "files", "worth_looking_at", "needs"):
            assert field in item, field
