"""Five items for a brochure site, and every one of them re-read the folder.

"Build a website for an Italian restaurant called LUMI in New York City."
Claude Code, asked the same thing directly, produced a good page in about
two minutes. This produced five items, a `node:http` server, a timezone
and daylight-saving module with its own suite, and spent six minutes on
the first item before it was stopped.

Two separate faults, both visible in the run record.

The plan invented its own spine. Item 2's criteria read, in full, "From
what was asked: nothing specific - this is all decided here", and items 3
and 5 then depended on it. Nobody asked for live opening hours. The
two-group split was doing its job as a label and nothing acted on the
label, so a reading the planner liked was given the same weight as the
thing the person wanted - and became the thing everything else waited
for. The split was not a split either: every item needed the first, which
is one item and four of its paragraphs, each paying a full round of
building, testing, diff-reading and reviewing.

And nothing was handed on. `Start` works out the toolchain, the run
command, the test command, what is in the repository and what to watch
for, writes all of it onto `run.inventory` - and the only thing that ever
read it was the command line's own printout. So each engineer began by
working out the language and the test command again. Five items, five
discoveries, one repository that had not changed.

The handoff is the facts, not instructions, and it says it is as of the
start of the run: a fact about a tree stops being a fact when the tree
changes, and the first item of a greenfield job changes most of them.
"""

from pathlib import Path

from drydock import engineer, orchestrate, start
from drydock.models import Inventory, Item
from drydock.run import Run

SYSTEM = " ".join(start.SYSTEM.split())
PLANNER = " ".join(Path("src/drydock/planner.py").read_text().split())


def a_run(task="a website for an Italian restaurant called LUMI", **chain):
    run = Run.start(Path("/x"), task)
    if chain:
        run.inventory = Inventory(
            build_tool=chain.get("build_tool", ""),
            language=chain.get("language", ""),
            test_command=chain.get("test_command", ""),
            build_command=chain.get("build_command", ""),
            source_files=chain.get("source_files", 0),
            test_files=chain.get("test_files", 0),
            findings=chain.get("findings", []),
            risks=chain.get("risks", []),
        )
    return run


class TestAnItemNobodyAskedForIsNotAnItem:
    def test_the_rule_is_stated(self):
        assert "**An item nobody asked for is not an item.**" in SYSTEM

    def test_the_empty_group_is_named_as_the_signal(self):
        """The exact words LUMI's item 2 wrote about itself."""
        assert "nothing specific, this is all decided here" in SYSTEM
        assert 'whose "From what was asked" group is empty' in SYSTEM

    def test_a_decision_may_shape_how_but_not_why(self):
        assert "may shape **how** an item is done" in SYSTEM
        assert "may not be **why** an item exists" in SYSTEM

    def test_the_schema_says_it_too(self):
        """A worker that reads only the field description gets it."""
        assert "is a feature you invented" in PLANNER
        assert "or it does not exist" in PLANNER

    def test_the_two_groups_still_exist(self):
        """The label is not removed - it is the thing being acted on."""
        assert "From what was asked:" in SYSTEM
        assert "Decided here:" in SYSTEM


class TestSplittingHasToEarnItself:
    def test_the_dependency_count_is_the_test(self):
        assert "Count the dependencies before you believe your own split" in SYSTEM
        assert "one item and four of its paragraphs" in SYSTEM

    def test_the_spine_sentence_is_named(self):
        """LUMI's own summary said the first item "lays the spine"."""
        assert 'says the first item "lays the spine"' in SYSTEM

    def test_the_measurement_is_quoted_rather_than_asserted(self):
        assert "six items took twenty-six minutes" in SYSTEM
        assert "the single item produced the better page" in SYSTEM

    def test_one_item_is_still_a_real_answer(self):
        assert "**One item is a real answer.**" in SYSTEM

    def test_genuine_parallel_work_is_still_allowed(self):
        """Not a rule against splitting - a rule against splitting a
        chain."""
        assert "the pieces can fail on their own and can be worked on at" in SYSTEM
        assert "different files, different data, different endpoints" in SYSTEM


class TestInventedInfrastructure:
    def test_the_least_machinery_rule_exists(self):
        assert "**The least machinery that answers the request.**" in SYSTEM

    def test_a_page_and_a_stylesheet_is_a_complete_answer(self):
        assert "A page of text and a stylesheet is a complete answer" in SYSTEM

    def test_infrastructure_has_to_point_at_the_request(self):
        assert "say in the item's reasoning which words in the request" in SYSTEM
        assert "If you cannot point at any, do not plan it" in SYSTEM

    def test_the_case_that_caused_it_is_written_down(self):
        assert "a timezone and daylight-saving module with its own test" in SYSTEM
        assert "Nobody asked for live opening hours" in SYSTEM


class TestTheHandoffCarriesWhatWasFound:
    def test_a_run_that_found_nothing_hands_on_nothing(self):
        assert a_run().handoff == ""

    def test_an_empty_inventory_is_not_an_empty_heading(self):
        assert a_run(build_tool="", language="", test_command="").handoff == ""

    def test_the_toolchain_and_the_commands(self):
        said = a_run(
            build_tool="npm",
            language="javascript",
            build_command="npm start",
            test_command="npm test",
        ).handoff
        assert "Built with: npm" in said
        assert "Language: javascript" in said
        assert "Run it with: `npm start`" in said
        assert "Test it with: `npm test`" in said

    def test_an_unknown_language_is_not_reported_as_one(self):
        said = a_run(build_tool="npm", language="unknown").handoff
        assert "Language" not in said

    def test_what_was_found_and_what_to_watch(self):
        said = a_run(
            build_tool="npm",
            findings=["The repository is empty."],
            risks=["Placeholder facts read as real."],
        ).handoff
        assert "Found: The repository is empty." in said
        assert "Watch: Placeholder facts read as real." in said

    def test_it_stays_short(self):
        """A handoff, not a briefing. Twenty findings is the analyst's
        printout, not something an engineer reads before working."""
        said = a_run(
            build_tool="npm",
            findings=[f"finding {n}" for n in range(20)],
            risks=[f"risk {n}" for n in range(20)],
        ).handoff
        assert said.count("- Found:") == 5
        assert said.count("- Watch:") == 3

    def test_a_long_finding_is_cut_rather_than_carried_whole(self):
        said = a_run(build_tool="npm", findings=["x" * 2000]).handoff
        assert len(said) < 1800


class TestItIsNotTrustedBlindly:
    def test_it_says_when_it_was_read(self):
        said = a_run(build_tool="npm").handoff
        assert "when this run started" in said
        assert "It was read once, at the start" in said

    def test_what_is_in_front_of_the_engineer_wins(self):
        said = a_run(build_tool="npm").handoff
        assert "what you see is right and this is stale" in said

    def test_checking_is_invited_rather_than_forbidden(self):
        said = a_run(build_tool="npm").handoff
        assert "Check anything you are about to rely on" in said
        assert "replaces the routine look around, not your judgement" in said

    def test_it_does_not_claim_to_be_the_item(self):
        """Facts, not instructions. What the work is still comes from
        the item and the brief."""
        said = a_run(build_tool="npm", findings=["f"], risks=["r"]).handoff
        assert "you do not spend your turns finding it again" in said
        for word in ("you must", "do not change", "required"):
            assert word not in said.lower()


class TestTheEngineerIsHandedIt:
    def test_the_prompt_has_somewhere_for_it(self):
        assert "{known}" in engineer.PROMPT

    def test_it_comes_before_the_work(self):
        said = engineer.PROMPT
        assert said.index("{known}") < said.index("{task}")
        assert said.index("{known}") < said.index("{criteria}")

    def test_work_takes_it(self):
        import inspect

        assert "known" in inspect.signature(engineer.work).parameters

    def test_the_loop_passes_the_run_s_own(self):
        import inspect

        assert "run.handoff," in inspect.getsource(orchestrate._one_item)

    def test_an_empty_handoff_still_renders(self):
        said = engineer.PROMPT.format(
            repo="r",
            build_command="npm test",
            shell="s",
            known="",
            task="t",
            id=1,
            title="x",
            rationale="y",
            files="a.js",
            verify_with="tests",
            criteria="c",
        )
        assert said

    def test_every_attempt_gets_it_rather_than_only_the_first(self):
        """The retry is the attempt that must not fail. Making it
        rediscover what the first one was told is the opposite."""
        import inspect

        body = inspect.getsource(orchestrate._one_item)
        assert body.count("report, usage = work(") == 1


class TestTheOtherStationsAreNotGivenNoise:
    def test_the_reviewer_is_not_handed_the_toolchain(self):
        """It reads a diff against criteria. A build command is not
        relevant to either, and this asked for the relevant thing only."""
        from drydock import reviewer

        assert "{known}" not in reviewer.PROMPT
        assert "Test it with" not in reviewer.PROMPT

    def test_the_reviewer_still_gets_what_it_does_need(self):
        from drydock import reviewer

        for field in ("{brief}", "{criteria}", "{files}", "{diff}"):
            assert field in reviewer.PROMPT, field

    def test_the_critic_still_judges_pictures_rather_than_a_report(self):
        from drydock import critic

        assert "{brief}" in critic.PROMPT
        assert "{direction}" in critic.PROMPT
        assert "{known}" not in critic.PROMPT


# The four shapes asked for. None calls a model: what is testable without
# one is whether the facts reach the station that needs them, with the
# ranking and the staleness warning intact.


class TestAGreenfieldRestaurantSite:
    def test_the_engineer_is_told_it_is_empty_rather_than_finding_out(self):
        run = a_run(
            build_tool="Node 22, no framework",
            build_command="npm start",
            test_command="npm test",
            findings=["The repository is empty: one commit, no files tracked."],
        )
        said = run.handoff
        assert "The repository is empty" in said
        assert "npm test" in said

    def test_the_request_still_outranks_everything(self):
        run = a_run()
        run.expanded = "The page should say whether the door is open right now."
        assert run.as_briefed.index("LUMI") < run.as_briefed.index("open right now")
        assert "anything here that disagrees with it is wrong and loses" in (
            run.as_briefed
        )

    def test_an_assumption_is_not_in_what_anybody_is_judged_on(self):
        run = a_run()
        run.assumptions = ["the page says whether the door is open right now"]
        assert "open right now" not in run.as_briefed
        assert "open right now" not in run.handoff


class TestAnExistingApplication:
    def test_its_conventions_are_handed_on_rather_than_rederived(self):
        run = a_run(
            task="add a /health endpoint",
            build_tool="maven",
            language="java",
            build_command="mvn -q package",
            test_command="mvn -q test",
            findings=["Controllers live in src/main/java/app/web and are thin."],
        )
        said = run.handoff
        assert "Built with: maven" in said
        assert "mvn -q test" in said
        assert "Controllers live in" in said

    def test_the_engineer_may_still_disagree_with_them(self):
        run = a_run(task="x", build_tool="maven", test_command="mvn -q test")
        assert "what you see is right and this is stale" in run.handoff


class TestABackendApiTask:
    def test_the_risks_reach_the_one_writing_the_code(self):
        run = a_run(
            task="make POST /payments idempotent",
            build_tool="npm",
            test_command="npm test",
            risks=["Two concurrent duplicates must not both proceed."],
        )
        assert "Watch: Two concurrent duplicates" in run.handoff

    def test_it_is_not_given_a_design_direction_it_has_no_use_for(self):
        run = a_run(task="make POST /payments idempotent", build_tool="npm")
        run.direction = "a warm room, oxblood and linen"
        assert run.direction not in run.handoff


class TestWhenRediscoveryIsTheRightAnswer:
    def test_the_build_command_is_read_fresh_every_item(self):
        """A greenfield job has no package.json until the first item
        writes one. The handoff says what was true at the start; the
        command the engineer is held to is detected again."""
        import inspect

        body = inspect.getsource(orchestrate._one_item)
        assert "detect(where).build_command" in body

    def test_the_verification_commands_are_detected_per_item(self):
        import inspect

        assert "detect(where)" in inspect.getsource(orchestrate._verification_commands)

    def test_nothing_here_skips_a_gate(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "if verdict.passed and unverified:" in source
        assert "here.discard()" in source
        assert source.count("_stopping(should_stop)") >= 5

    def test_the_critic_still_looks_rather_than_reading_the_handoff(self):
        import inspect

        body = inspect.getsource(orchestrate._show_it)
        assert "look_at_it(" in body
        assert "run.handoff" not in body

    def test_the_inspector_and_the_verifier_are_untouched(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "report_card = look(" in source
        assert "verdict = verify(" in source


class TestNothingProtectiveWasTraded:
    def test_the_deadline_still_works(self):
        from drydock.session import Session

        assert Session(Path("/tmp"), "t", [], within_minutes=20).within_minutes == 20

    def test_the_confinement_is_untouched(self):
        source = Path("src/drydock/engines.py").read_text()
        assert '"matcher": "Bash|Read|Edit|Write|Glob|Grep|NotebookEdit"' in source
        assert "*SETTING_SOURCES," in source

    def test_the_attempt_bound_is_untouched(self):
        from drydock.policy import BALANCED, DEEP, PROFILES

        assert PROFILES[BALANCED].attempts == 2
        assert PROFILES[DEEP].attempts == 3

    def test_an_item_is_still_its_own_commit(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "here.commit(" in source
        assert "here.sweep()" in source

    def test_the_handoff_is_not_a_new_agent_or_a_store(self):
        """It is a property on a record that already existed, built
        from a field that was already written."""
        assert "handoff" in dir(Run)
        assert isinstance(Run.handoff, property)
        source = Path("src/drydock/run.py").read_text()
        assert "self.inventory" in source[source.index("def handoff") :][:2200]


def _an_item() -> Item:
    return Item(
        id=1,
        title="t",
        plain="p",
        rationale="r",
        files=["a.js"],
        verify_with="tests",
    )


class TestTheHandoffDoesNotWidenScope:
    def test_the_item_is_still_the_whole_of_the_scope(self):
        assert "Your item, which is the entire scope" in engineer.PROMPT

    def test_the_handoff_sits_above_that_rather_than_replacing_it(self):
        said = engineer.PROMPT
        assert said.index("{known}") < said.index("Your item, which is the entire")

    def test_the_files_an_item_authorises_are_unchanged(self):
        assert _an_item().files == ["a.js"]
