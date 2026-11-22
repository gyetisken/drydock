"""Who decides how the thing is built.

The Corso run is the case. A bicycle shop's one page, Opus on every
station, six items, no refusals, twelve tests green - and a page that was
not as good as the model that built it. The reason is in the record: the
direction was eight thousand characters of stylesheet written in prose,
down to `row padding 0.625rem 0` and `letter-spacing 0.01em - POSITIVE, a
hair`, and the item's own rationale said why - "the specific values exist
so the engineer does not have to invent them".

So it did not invent them. It transcribed them. The desktop layout sits
flush against the left edge with nine hundred pixels of nothing beside it
because the direction said "not auto-centred on desktop either", and the
critic approved it because the critic was asked whether the page carried
out the direction, which it did, perfectly.

Three stations, one failure: the decision was taken before anybody had
seen a page, by a station that could not see one, and every station after
it was measuring against that decision rather than against what the person
actually asked for.

What these tests hold is the principle, not the wording: say what the
outcome has to be, let whoever is in front of the code decide how, and
check the result against what was asked for.
"""

import inspect

from drydock import critic, designer, engineer, orchestrate, planner, session, start
from drydock.planner import PLAN_SCHEMA


def flat(text: str) -> str:
    """One line, so an assertion is not a claim about where it wraps."""
    return " ".join(text.split())


class TestTheDesignerDirectsIntent:
    """It was being asked for a stylesheet and it delivered one."""

    def test_it_no_longer_asks_for_the_values_as_a_deliverable(self):
        said = flat(designer.SYSTEM)
        assert "hex values with their contrast ratios" not in said
        assert "a type scale in rem, a spacing scale" not in said

    def test_it_says_those_belong_to_the_engineer(self):
        said = flat(designer.SYSTEM)
        assert "Everything else is the engineer's" in said
        for theirs in ("hex", "type scale in rem", "spacing scale", "breakpoints"):
            assert theirs in said, theirs

    def test_the_same_on_the_path_that_is_actually_used(self):
        """`planner.py` and `designer.py` are the four-station path, which
        is behind an environment variable. The direction that produced
        Corso's came from start.LOOKED_AT, and a fix that only landed in
        the module named after the station would have changed nothing."""
        said = flat(start.LOOKED_AT)
        assert "Direct the intent, not the stylesheet" in said
        assert "leave the hex, the type scale in rem, the spacing scale" in said

    def test_the_engineer_is_no_longer_described_as_blind(self):
        """ "The engineer has your words and nothing else" was true when it
        was written and is the sentence that justified writing a
        stylesheet in prose. It has the repository, the brief, and a
        browser it renders the page in."""
        for said in (
            flat(designer.SYSTEM),
            flat(designer.PROMPT),
            flat(start.LOOKED_AT),
        ):
            assert "has your words and nothing else" not in said

    def test_what_the_person_asked_for_is_still_repeated_exactly(self):
        """Delegating the values must not lose the ones somebody chose."""
        assert "actually named" in flat(designer.SYSTEM)
        assert "is theirs and it is repeated here exactly" in flat(designer.SYSTEM)
        assert "is a constraint, and is repeated exactly" in flat(start.LOOKED_AT)

    def test_vagueness_is_named_as_the_other_failure(self):
        """The opposite ditch. "Clean and modern" directs nothing, and a
        direction that says nothing is how the generic version arrives."""
        assert "not a licence to be vague" in flat(designer.SYSTEM)
        assert "Being vague is the other failure" in flat(start.LOOKED_AT)

    def test_it_still_has_to_decide_the_things_that_are_its_own(self):
        """Composition, the one moment, the generic version - none of
        that is implementation and none of it moved."""
        said = designer.SYSTEM
        for kept in ("**Composition.**", "**One moment.**", "generic version"):
            assert kept in said, kept


class TestThePlannerPlansOutcomes:
    def test_an_item_says_what_must_be_true_not_how_to_type_it(self):
        said = flat(planner.SYSTEM)
        assert "Say what has to be true afterwards, not how to type it" in said
        assert "are the engineer's" in said

    def test_the_same_on_the_path_that_is_actually_used(self):
        said = flat(start.SYSTEM)
        assert "belong to the engineer" in said
        assert "transcription of your own guess" in said

    def test_an_implementation_detail_is_not_an_item(self):
        """Corso's item 1 put a meta tag in the head of a page item 3
        rewrote anyway: two lines, one full round of building, testing,
        diff-reading and reviewing."""
        for said in (flat(planner.SYSTEM), flat(start.SYSTEM)):
            assert "implementation detail of another item" in said

    def test_a_checking_item_is_not_an_item(self):
        """Corso's item 6 was "look at it on a phone-width viewport and
        run it green" - the verifier, the critic and the probe already do
        that on every item, and this one arrived after the thing it was
        meant to catch had been accepted."""
        for said in (flat(planner.SYSTEM), flat(start.SYSTEM)):
            assert "checking item" in said
            assert "already happening" in said

    def test_the_field_that_carried_the_prescription_says_so(self):
        """`rationale` is where Corso's padding values travelled."""
        item = PLAN_SCHEMA["properties"]["items"]["items"]
        said = flat(item["properties"]["rationale"]["description"])
        assert "Not the implementation" in said
        assert "the engineer's to choose" in said

    def test_constraints_somebody_fixed_are_still_stated_exactly(self):
        for said in (flat(planner.SYSTEM), flat(start.SYSTEM)):
            assert "constraint" in said

    def test_the_bounds_on_a_plan_did_not_move(self):
        """Fewest items, one sitting, the first item leaves something
        that runs. Loosening the dictation is not loosening the plan."""
        for kept in (
            "As few items as the work honestly needs",
            "The first item leaves something that runs",
            "{fewest} to {most} items for this job",
        ):
            assert kept in planner.SYSTEM, kept


class TestTheEngineerDecides:
    def test_it_is_told_the_implementation_is_its_own(self):
        said = flat(engineer.SYSTEM)
        assert "What is yours to decide" in said
        for mine in ("Layout", "typography", "spacing", "hierarchy", "markup"):
            assert mine in said, mine

    def test_it_is_told_to_decide_rather_than_wait(self):
        said = flat(engineer.SYSTEM)
        assert "you are not waiting for permission" in said
        assert '"It did not say" is not a reason for the obvious version' in said

    def test_what_somebody_fixed_is_still_a_constraint(self):
        said = flat(engineer.SYSTEM)
        assert "that is a constraint somebody chose and it holds" in said

    def test_the_brief_outranks_everything_downstream(self):
        """Corso's direction drifted from the brief and nothing could
        say so: the engineer was given the item, the critic the
        direction, and the brief was nobody's standard."""
        said = flat(engineer.SYSTEM)
        assert "what the finished thing is judged against" in said
        assert "including the direction" in said

    def test_the_brief_still_reaches_it(self):
        assert "{task}" in engineer.PROMPT
        assert "for context only" not in engineer.PROMPT

    def test_nothing_that_holds_the_work_together_was_loosened(self):
        """Scope, the test rule, and not proving its own work. Giving it
        discretion over how is not giving it discretion over what."""
        for kept in (
            "The item you are given is the entire scope",
            "Do not touch the verification",
            "Running the full suite yourself afterwards",
        ):
            assert kept in engineer.SYSTEM, kept


class TestTheCriticJudgesThePage:
    def test_the_brief_is_what_it_judges_against(self):
        said = flat(critic.SYSTEM)
        assert "judged against is the brief" in said

    def test_the_direction_is_context_rather_than_the_standard(self):
        said = flat(critic.SYSTEM)
        assert "matching it is not the standard" in said
        assert "departing from it is not a fault" in said

    def test_following_the_direction_is_not_enough_on_its_own(self):
        """The Corso sentence. A page that follows the direction to the
        letter and is still a bad page was being approved for following
        it."""
        said = flat(critic.SYSTEM)
        assert "follows the direction to the letter and is still a bad page" in said
        assert "never a reason on their own" in said

    def test_the_old_standard_is_gone(self):
        assert "Reject when the page does not carry out the direction" not in flat(
            critic.SYSTEM
        )
        assert "did this item put its part of the direction on the page" not in flat(
            critic.PROMPT
        )

    def test_the_prompt_carries_the_brief_and_labels_the_direction(self):
        assert "{brief}" in critic.PROMPT
        assert "{direction}" in critic.PROMPT
        said = flat(critic.PROMPT)
        assert said.index("{brief}") < said.index("{direction}")
        assert "Context for what was intended, not the standard" in said

    def test_a_run_without_one_says_so_rather_than_inventing_one(self):
        """An older record, or a station with no brief to hand, must not
        leave the critic reading an empty heading as though the person
        had asked for nothing."""
        source = inspect.getsource(critic.look)
        assert '"(not recorded for this run)"' in source
        assert '"(none was written)"' in source

    def test_look_takes_a_brief(self):
        assert "brief" in inspect.signature(critic.look).parameters

    def test_both_callers_hand_it_the_brief(self):
        assert "brief=run.as_briefed," in inspect.getsource(orchestrate._show_it)
        assert "brief=self.run.as_briefed," in inspect.getsource(
            session.Session._look_at_the_finished_thing
        )

    def test_the_objective_checks_it_must_keep(self):
        """Overflow, clipping and unreadable contrast are not matters of
        opinion and are refused whoever introduced them."""
        said = flat(critic.SYSTEM)
        assert "text that overflows or is clipped at either width" in said
        assert "text a person cannot read against its background" in said

    def test_it_still_judges_one_item_rather_than_the_whole_page(self):
        assert "Judge this item, not the whole page" in critic.SYSTEM

    def test_what_is_measured_is_still_measured_before_anybody_looks(self):
        """The critic having a freer hand must not turn a measurement
        into an opinion. The probe and the overflow check run first and
        can refuse on their own."""
        source = inspect.getsource(orchestrate._show_it)
        assert "why_it_does_not_fit(" in source
        assert "probe.look(" in source
        assert source.index("why_it_does_not_fit(") < source.index("look_at_it(")


class TestNothingIndependentWasRemoved:
    def test_every_gate_still_runs(self):
        source = inspect.getsource(orchestrate._judge)
        for gate in ("review", "_show_it"):
            assert gate in source, gate

    def test_an_item_that_fails_is_still_thrown_away(self):
        source = inspect.getsource(orchestrate._one_item)
        assert "here.discard()" in source

    def test_the_engineer_still_cannot_change_the_tests(self):
        assert "Changing a test so it passes" in engineer.SYSTEM
