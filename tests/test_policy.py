"""How much ceremony a job gets.

Every number that decided how hard this program works was a constant in
whichever module happened to need it - six files, no single place to see
them, and no way to say "this is a one-line fix, do not spend forty
minutes on it".

What matters here is that the default is unchanged, that the cheap profile
is cheaper in the ways that are allowed and in no others, and that the
three things which make the output believable cannot be switched off.
"""

import pytest

from drydock.policy import (
    AT_THE_END,
    BALANCED,
    DEEP,
    EVERY_ITEM,
    FAST,
    PROFILES,
    Policy,
    as_told,
    at_least,
    of,
)


class TestTheDefaultDidNotMove:
    """A default that changes under somebody is not a default. These are
    the numbers this program ran on before profiles existed, and the
    balanced profile has to be exactly them."""

    def test_the_balanced_profile_is_what_was_there_before(self):
        it = of(BALANCED)
        assert (it.turns, it.minutes, it.retry_minutes) == (60, 12.0, 18.0)
        assert (it.attempts, it.revivals) == (2, 2)
        assert it.read_the_diff is True
        assert it.look_at_it == EVERY_ITEM
        assert it.build_as_well is True

    def test_an_unknown_name_is_the_default(self):
        assert of("enthusiastic").profile == BALANCED
        assert of(None).profile == BALANCED
        assert of("").profile == BALANCED

    def test_the_name_is_read_loosely(self):
        assert of("  FAST  ").profile == FAST


class TestTheCheapProfile:
    def test_it_asks_for_fewer_items(self):
        """Each item costs three or four minutes of being checked whatever
        is in it, so the saving is in the count, not the contents."""
        assert of(FAST).most_items < of(BALANCED).most_items

    def test_it_does_not_read_the_diff(self):
        assert of(FAST).read_the_diff is False

    def test_it_looks_at_the_finished_thing_rather_than_every_step(self):
        assert of(FAST).look_at_it == AT_THE_END

    def test_it_does_not_give_the_engineer_less_time(self):
        """Cutting the checking is a choice. Cutting the work is just a
        worse result, slightly sooner."""
        assert of(FAST).turns == of(BALANCED).turns
        assert of(FAST).minutes == of(BALANCED).minutes

    def test_it_still_lets_a_failed_item_be_tried_again(self):
        assert of(FAST).attempts >= 2


class TestTheExpensiveProfile:
    def test_it_reads_the_diff_and_looks_at_the_page(self):
        assert of(DEEP).read_the_diff is True
        assert of(DEEP).look_at_it == EVERY_ITEM

    def test_it_gives_more_room(self):
        assert of(DEEP).attempts > of(BALANCED).attempts
        assert of(DEEP).minutes >= of(BALANCED).minutes


class TestWhatNoProfileCanTurnOff:
    """The inspector, the confinement and the commit-and-revert are not
    ceremony. They are the reason the output can be believed, and a
    profile that switched them off would be a different program - so there
    is deliberately no field for any of them."""

    @pytest.mark.parametrize("name", [FAST, BALANCED, DEEP])
    def test_there_is_no_switch_for_them(self, name):
        fields = set(vars(of(name)))
        assert not any(
            word in field
            for field in fields
            for word in ("inspect", "confine", "secret", "revert", "commit")
        )

    @pytest.mark.parametrize("name", [FAST, BALANCED, DEEP])
    def test_every_profile_still_builds_what_it_tests(self, name):
        """A change that breaks the build is invisible until some later
        item happens to be verified by one, and then it is six commits back
        and belongs to nobody."""
        assert of(name).build_as_well is True


class TestRaisingTheFloor:
    """Lowering is never automatic. Raising is, because the cost of being
    wrong about a migration is not symmetrical with the cost of twenty
    extra minutes."""

    def test_cheap_work_on_dangerous_ground_is_raised(self):
        assert at_least(of(FAST), DEEP).profile == DEEP

    def test_anything_already_stronger_is_left_alone(self):
        assert at_least(of(DEEP), BALANCED).profile == DEEP

    def test_the_same_profile_is_left_alone(self):
        assert at_least(of(FAST), FAST).profile == FAST

    def test_an_unknown_floor_does_not_lower_anything(self):
        assert at_least(of(DEEP), "whatever").profile == DEEP


class TestChangingOneThing:
    def test_a_caller_who_knows_better_can_say_so(self):
        it = as_told(of(FAST), attempts=5)
        assert it.attempts == 5
        assert it.profile == FAST

    def test_the_original_is_not_changed(self):
        before = of(FAST)
        as_told(before, attempts=5)
        assert of(FAST).attempts == before.attempts

    def test_a_policy_cannot_be_edited_in_place(self):
        """It is decided once and carried. Something that rewrites it
        mid-run would make the record of what was run untrue."""
        with pytest.raises(Exception):
            of(FAST).attempts = 9


class TestItSaysWhatItIs:
    @pytest.mark.parametrize("name", [FAST, BALANCED, DEEP])
    def test_every_profile_can_say_itself_in_one_line(self, name):
        said = of(name).say
        assert name in said
        assert "items" in said

    def test_the_line_says_whether_the_diff_is_read(self):
        assert "no diff review" in of(FAST).say
        assert "the diff is read" in of(DEEP).say

    def test_the_line_says_when_the_page_is_looked_at(self):
        assert "once, at the end" in of(FAST).say
        assert "as it is built" in of(BALANCED).say


def test_every_named_profile_is_reachable():
    for name, policy in PROFILES.items():
        assert of(name) is policy
        assert isinstance(policy, Policy)


class TestNothingMovedWhenThePolicyArrived:
    """The policy replaced constants scattered across six files. The whole
    claim of this change is that it moved them without changing them, and
    a claim like that is worth a test rather than a careful reading."""

    def test_the_engineer_gets_what_it_always_got(self, monkeypatch):
        """Sixty turns, twelve minutes, eighteen on a retry."""
        from drydock import engineer

        seen = {}

        class Fake:
            def __init__(self, model="opus", max_turns=60, minutes=12.0):
                seen.update(model=model, max_turns=max_turns, minutes=minutes)

            def work(self, *a, **k):
                class Result:
                    done = True
                    summary = ""
                    files_changed: list = []
                    noticed: list = []
                    question = ""
                    died = False
                    dollars = 0.0
                    turns = 1

                return Result()

        monkeypatch.setattr(engineer, "ClaudeCodeEngine", Fake)
        monkeypatch.setattr(engineer, "briefing", lambda skills, role: "")
        from pathlib import Path

        from drydock.models import Item

        def run_it(retry_of: str, policy=None):
            engineer.work(
                Path("/tmp"),
                "a task",
                Item(id=1, title="t", rationale="r", files=[], verify_with="tests"),
                "npm run build",
                retry_of=retry_of,
                engine="claude",
                model="opus",
                policy=policy,
            )
            return dict(seen)

        first = run_it("")
        assert (first["max_turns"], first["minutes"]) == (60, 12.0)

        again = run_it("sent back")
        assert (again["max_turns"], again["minutes"]) == (60, 18.0)

        # and the cheap profile does not take the engineer's time away
        cheap = run_it("", of(FAST))
        assert (cheap["max_turns"], cheap["minutes"]) == (60, 12.0)

    def test_an_item_still_gets_two_attempts_and_two_restarts(self):
        it = of(BALANCED)
        assert it.attempts == 2
        assert it.revivals == 2

    def test_the_orchestrator_defaults_to_balanced(self):
        """execute() is called without a policy from several places, and
        every one of them used to get the behaviour balanced describes."""
        import inspect

        from drydock import orchestrate

        source = inspect.getsource(orchestrate.execute)
        assert "policy or of(None)" in source
        assert of(None).profile == BALANCED
