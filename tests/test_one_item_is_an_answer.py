"""A cohesive job had to be cut up to satisfy a number.

Corso is one page. It was planned twice and cut up both times: six items
under the old prompts, four under the new ones. Every item in both plans
edited `public/index.html` or `public/styles.css`, so none of them could
run beside another - the parallelism the decomposition is for was never
available - and each boundary was somewhere a correct change could be
refused for crossing it, which is what happened twice in the second run.

The floor was doing it. `fewest_items` was two on the cheapest profile
and four on the default, handed to the planner as "{fewest} to {most}
items for this job. That is not a suggestion". One item was not an
available answer.

Now it is, on FAST and BALANCED, with the test for when: one family of
files, one sitting, a failure in any part diagnosed by looking at the
others. DEEP keeps its floor - work where being wrong is expensive is the
work that wants separable pieces - and the gates are untouched either
way.
"""

import inspect

from drydock import orchestrate, planner, start
from drydock.policy import of


def flat(text: str) -> str:
    return " ".join(text.split())


class TestOneItemIsAvailable:
    def test_the_cheap_profile(self):
        assert of("fast").fewest_items == 1

    def test_the_default_profile(self):
        """What Corso ran under. The floor of four is why a single page
        became six items."""
        assert of("balanced").fewest_items == 1

    def test_the_careful_profile_keeps_its_floor(self):
        """Work where being wrong is expensive is the work that wants
        separable pieces, each its own commit and its own undo."""
        assert of("deep").fewest_items == 4

    def test_the_ceilings_did_not_move(self):
        assert of("fast").most_items == 3
        assert of("balanced").most_items == 7
        assert of("deep").most_items == 12


class TestThePlannerIsToldWhenOneIsRight:
    def test_both_planning_paths_carry_the_rule(self):
        """Corso's plan came from start.py; planner.py is the four-station
        path behind an environment variable. A rule in one of them is a
        rule in neither."""
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert "One item is a real answer" in said

    def test_the_test_for_cohesion_is_stated(self):
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert "one family of files, written in one sitting" in said
            assert "diagnosed by looking at the others" in said

    def test_the_cost_of_splitting_is_stated(self):
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert "none of them can run beside another" in said
            assert "refused for crossing it" in said

    def test_when_several_items_are_right_is_still_stated(self):
        """This must not read as "always one item"."""
        for said in (flat(start.SYSTEM), flat(planner.SYSTEM)):
            assert (
                "Several items are right when the pieces can fail on their own" in said
            )
            assert "different files, different data, different endpoints" in said

    def test_the_range_no_longer_reads_as_a_floor_to_reach(self):
        said = flat(planner.SYSTEM)
        assert "is not a target to reach" in said
        assert "That is not a suggestion and it is not a target to fill" not in said

    def test_the_ceiling_is_still_a_ceiling(self):
        assert "{most} is a ceiling" in flat(planner.SYSTEM)


class TestAOneItemPlanStillGetsEverything:
    def test_it_runs_in_the_repository_rather_than_a_worktree(self):
        """One item needs no isolation from itself, and the worktree is
        the expensive part of a wave."""
        source = inspect.getsource(orchestrate._work_a_wave)
        assert "if len(items) == 1:" in source
        one = source[source.index("if len(items) == 1:") :]
        assert "_one_item(" in one[:400]
        assert "repo.worktree(" not in one[: one.index("trees: dict")]

    def test_every_gate_still_runs_for_it(self):
        """The reason this is safe: the checking is per item, not per
        plan, so one item is checked exactly as six were."""
        source = inspect.getsource(orchestrate._one_item)
        for gate in ("verify(", "look(", "_judge("):
            assert gate in source, gate

    def test_it_is_still_discarded_when_it_fails(self):
        assert "here.discard()" in inspect.getsource(orchestrate._one_item)

    def test_the_stop_checks_apply_to_it_too(self):
        assert "_stopping(should_stop)" in inspect.getsource(orchestrate._one_item)


class TestNothingAboutDecompositionWasRemoved:
    def test_the_seam_rule_is_untouched(self):
        assert "if two pieces would always be written in the same" in flat(
            planner.SYSTEM
        )

    def test_the_parallel_shaping_advice_is_untouched(self):
        assert "Shape the work so it can be done at once" in planner.SYSTEM

    def test_dependencies_are_still_asked_for(self):
        assert "Say what each item actually needs" in planner.SYSTEM

    def test_waves_still_exist(self):
        source = inspect.getsource(orchestrate.execute)
        assert "plan_waves(" in source
        assert "_work_a_wave(" in source
