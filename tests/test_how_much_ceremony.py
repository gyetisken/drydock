"""A short sentence about a dangerous thing reads like a short sentence.

`intent.read` routes "fix the login password hash" to `/fix`, which is
the path with no planner, no acceptance criteria and no approval. So do
"change the api key handling", "drop the users table and rebuild it" and
"remove the old payment retry". The floor calls all four deep, raised the
attempts and the turns for each, and the branch that skips the planning
never read it.

That is the whole of the hole: the floor was consulted where the *plan*
decides to skip approval, and not where the *router* decides to skip
planning. One condition, in the place the decision is actually made.

The three depths were already here under other names - `/fix` goes
straight to the work, a plan that nothing raised and that came back as
one item skips the approval, and anything else is shown first. What was
missing was a way to say which you wanted, and any sign of which you
were given.
"""

from pathlib import Path

import pytest

from drydock import intent
from drydock.policy import BALANCED, DEEP, FAST, PROFILES, at_least, floor_for, of

SESSION = Path("src/drydock/session.py").read_text()
JS = Path("src/drydock/static/chat.js").read_text()
PAGE = Path("src/drydock/web.py").read_text()

RISKY_AND_SHORT = (
    "fix the login password hash",
    "change the api key handling",
    "drop the users table and rebuild it",
    "remove the old payment retry",
    "fix the oauth token refresh",
)
SMALL_AND_SAFE = (
    "fix the typo in the footer",
    "rename the header to Home",
    "change the button colour to green",
)


class TestTheRouterStillRoutes:
    @pytest.mark.parametrize("said", RISKY_AND_SHORT + SMALL_AND_SAFE)
    def test_a_small_sentence_still_reads_as_a_small_change(self, said):
        """The router is not what was wrong. It reads sentences, and
        these are small sentences."""
        assert intent.read(said).command == "/fix"

    def test_it_is_still_deterministic(self):
        assert intent.read("fix the typo") == intent.read("fix the typo")

    def test_naming_a_command_still_wins(self):
        said = intent.read("/plan rewrite the parser")
        assert said.command == "/plan"
        assert said.sure


class TestTheFloorIsReadWhereTheDecisionIsMade:
    @pytest.mark.parametrize("said", RISKY_AND_SHORT)
    def test_risky_work_has_a_floor(self, said):
        assert floor_for(said).floor == DEEP, said

    @pytest.mark.parametrize("said", SMALL_AND_SAFE)
    def test_ordinary_work_does_not(self, said):
        assert floor_for(said).floor == "", said

    def test_the_straight_path_now_consults_it(self):
        assert 'if self.stop_after == "straight" and self.floor:' in SESSION

    def test_it_turns_into_the_planned_path_rather_than_a_refusal(self):
        block = SESSION[SESSION.index('if self.stop_after == "straight" and') :][:900]
        assert 'self.stop_after = "planner"' in block

    def test_it_says_why_rather_than_quietly_changing_course(self):
        block = SESSION[SESSION.index('if self.stop_after == "straight" and') :][:900]
        assert '"plan.required"' in block
        assert "why=self.floor" in block

    def test_the_check_comes_before_the_plan_is_faked(self):
        """The straight path builds its own one-item plan. Reading the
        floor after that would be reading it too late."""
        assert SESSION.index('if self.stop_after == "straight" and self.floor:') < (
            SESSION.index('summary="One change, done directly."')
        )

    def test_the_floor_still_raises_the_policy_as_well(self):
        assert at_least(of(FAST), DEEP).profile == DEEP
        assert at_least(of(DEEP), "").profile == DEEP


class TestTheThreeDepthsExist:
    def test_fast_is_a_path_with_no_planner_call(self):
        """It builds its one item locally. No model is asked anything
        before the engineer starts."""
        # Wide enough to hold the block and its reasoning. It was 2,000
        # and a comment explaining why the item now says whether anybody
        # looks at it pushed the call past the end of the slice.
        block = SESSION[SESSION.index('if self.stop_after == "straight":') :][:3200]
        assert "self.run.plan = Plan(" in block
        assert "begin(" not in block
        assert "self.work_the_plan()" in block

    def test_fast_still_runs_every_gate(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        for gate in ("verdict = verify(", "report_card = look(", "_judge("):
            assert gate in source, gate

    def test_brief_is_a_plan_that_skips_only_the_approval(self):
        block = SESSION[SESSION.index("straight = (") :][:400]
        assert "not self.floor" in block
        assert "not started.needs_a_plan" in block
        assert "len(started.plan.items) <= 1" in block

    def test_deep_is_the_default_when_nothing_says_otherwise(self):
        assert of("").profile == BALANCED
        assert PROFILES[DEEP].attempts > PROFILES[BALANCED].attempts
        assert PROFILES[DEEP].turns > PROFILES[BALANCED].turns
        assert PROFILES[DEEP].minutes > PROFILES[BALANCED].minutes


class TestAPersonCanSayWhichTheyWant:
    def test_there_is_a_control(self):
        assert 'id="pick-depth"' in PAGE
        assert 'id="pop-depth"' in PAGE

    def test_it_offers_the_three_and_a_default(self):
        said = JS[JS.index("const DEPTHS = [") :][:900]
        for mode in ('id: ""', 'id: "fast"', 'id: "balanced"', 'id: "deep"'):
            assert mode in said, mode

    def test_deciding_for_you_is_the_default(self):
        assert 'depth: "" }' in JS
        said = JS[JS.index("const DEPTHS = [") :][:400]
        assert said.index('id: ""') < said.index('id: "fast"')

    def test_what_it_picks_is_sent(self):
        assert "profile: S.depth," in JS

    def test_the_api_has_always_taken_it(self):
        from drydock.web import StartJob

        assert StartJob(project="/x", command="/do a", profile="deep").profile == "deep"
        assert StartJob(project="/x", command="/do a").profile == ""

    def test_it_is_remembered(self):
        assert 'localStorage.setItem("drydock.depth", S.depth)' in JS
        assert 'localStorage.getItem("drydock.depth")' in JS


class TestTheAutomaticDecisionIsVisible:
    def test_a_raised_floor_is_said_in_the_window(self):
        """It was emitted and nothing listened, so a run that had been
        quietly made more careful looked like one that had not."""
        assert '"policy.raised": (e)' in JS
        assert "Taking this one seriously" in JS

    def test_it_says_it_can_be_overruled(self):
        said = JS[JS.index('"policy.raised": (e)') :][:600]
        assert "You can overrule" in said

    def test_a_plan_forced_onto_a_small_change_is_said_too(self):
        assert '"plan.required": (e)' in JS
        said = " ".join(JS[JS.index('"plan.required": (e)') :][:900].split())
        assert "This one gets a plan" in said
        assert "what it names decides this rather than how long it is" in said

    def test_skipping_the_plan_was_always_said(self):
        assert '"plan.skipped": (e)' in JS


class TestNothingWasWeakenedToGetHere:
    def test_the_scope_check_is_untouched(self):
        source = Path("src/drydock/inspect.py").read_text()
        assert "which the item did not name" in source

    def test_stop_deadline_rollback_and_checkpoint(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert source.count("_stopping(should_stop)") >= 5
        assert "here.discard()" in source
        assert source.count("here.checkpoint(") >= 2

    def test_the_isolation_is_untouched(self):
        source = Path("src/drydock/engines.py").read_text()
        assert '"matcher": "Bash|Read|Edit|Write|Glob|Grep|NotebookEdit"' in source
        assert '"--setting-sources",' in source
        assert '"--strict-mcp-config",' in source
        assert "AUTH_THAT_IS_NOT_OURS" in source

    def test_no_limit_was_added(self):
        assert PROFILES[BALANCED].turns == 60
        assert PROFILES[BALANCED].minutes == 12.0

    def test_approval_is_still_required_where_it_was(self):
        assert '"awaiting.approval"' in SESSION


class TestFastKnowsWhatItCannotCheck:
    def test_the_file_scope_check_needs_a_file_list(self):
        """An honest limitation, not a fix: the straight path has no
        plan, so there is no list of authorised files and the
        arithmetic scope check has nothing to measure against. The
        reviewer still reads the diff against the request, and the rest
        of the inspector - tests removed, assertions weakened, secrets -
        runs as it always does."""
        from drydock.inspect import _outside

        assert _outside("+++ b/anything.py\n", []) == []
        assert _outside("+++ b/anything.py\n", ["other.py"]) == ["anything.py"]

    def test_the_rest_of_the_inspector_does_not_need_one(self):
        source = Path("src/drydock/inspect.py").read_text()
        for check in ("allow_removals", "MAGIC"):
            assert check in source, check


class TestTheNamesAreTrue:
    """Two of the four said something the system did not do.

    "Straight to it" sent `profile: "fast"`, which changed how much
    ceremony the work got and left the route to the sentence - so
    somebody who asked for no plan watched a planner run. And "the
    checks all still run" was not true of that profile: it turns the
    diff review off and looks at the finished thing once rather than at
    every step.
    """

    def names(self) -> dict:
        import re

        block = JS[
            JS.index("const DEPTHS = [") : JS.index("];", JS.index("const DEPTHS = ["))
        ]
        return dict(re.findall(r'id: "(\w*)", label: "([^"]+)"', block))

    def test_they_are_short_and_plain(self):
        said = self.names()
        assert said == {
            "": "Automatic",
            "fast": "No plan",
            "balanced": "Plan first",
            "deep": "Extra careful",
        }

    def test_no_plan_actually_skips_the_plan(self):
        said = PAGE
        assert 'if body.profile == "fast" and stop_after == "planner":' in said
        assert 'stop_after = "straight"' in said

    def test_it_only_redirects_the_path_that_would_have_planned(self):
        """`/ask`, `/review`, `/qa` and the rest are not plans and are
        not touched."""
        block = PAGE[PAGE.index('if body.profile == "fast"') :][:200]
        assert 'stop_after == "planner"' in block

    def test_the_floor_still_overrules_it(self):
        assert 'if self.stop_after == "straight" and self.floor:' in SESSION

    def test_the_note_no_longer_claims_every_check_runs(self):
        said = JS[JS.index("const DEPTHS = [") :][:1200]
        assert "the checks all still run" not in said
        assert "the diff review is skipped" in said

    def test_the_note_says_what_does_still_run(self):
        said = JS[JS.index("const DEPTHS = [") :][:1200]
        assert "Build, tests and the scope check still run" in said

    def test_the_fast_profile_really_is_that(self):
        """Saying so would be worse than useless if it were not."""
        from drydock.policy import AT_THE_END

        assert PROFILES[FAST].read_the_diff is False
        assert PROFILES[FAST].look_at_it == AT_THE_END

    def test_extra_careful_really_does_split_into_four(self):
        assert PROFILES[DEEP].fewest_items == 4
        assert PROFILES[DEEP].attempts == 3
