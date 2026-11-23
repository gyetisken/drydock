"""FAST was not the planned path with fewer checks. It was no reading at all.

Two runs of the same hotel, four hours apart, same two skills, one item
each, one attempt each:

                      planned      FAST
    direction          4,515 ch        0
    brief              1,630 ch        0
    assumptions               7        0
    drydock-look              2        0
    logo drawn              yes       no
    tests recorded           27        0  (22 had actually passed)

Nothing in that column was a policy decision. The FAST profile asks for
`self_looks=2` and `look_at_it=AT_THE_END`; every one of those zeroes is
somewhere the harness dropped what the policy had already asked for, or
never called the thing that produces it.

`_worth_a_look` decides whether the engineer gets the look command. It
reads `item.worth_looking_at` and falls back to the item's files - and the
straight path builds its one item with `files=[]` and nothing else, so the
answer was no for every straight run, every website included. The engineer
spent part of its item trying to install a headless browser and then wrote
"the layout is therefore reasoned rather than seen" in its own findings.

The design knowledge went the same way by a different route. `start.py`
replaced four stations and writes the direction, which is the designer's
job, but was handed only the plan section - so the whole of `## Design`
reached nobody except the worker that draws the logo: 3,531 characters of
how a page is composed and what may be done about photographs, delivered
to a worker whose entire output is one one-colour mark.

Pinned here: the look is restored by the item saying what it is rather
than by widening any rule, the design sections reach the stations that do
the designing, an undirected visual item directs itself inside the turn it
already has, and `verify_build` records the test count that was sitting in
its own output.
"""

import inspect
from pathlib import Path

from drydock import engineer, orchestrate, session, start
from drydock.models import Item
from drydock.policy import FAST, of
from drydock.session import Session
from drydock.skills import Skill, briefing, discover, load


def flat(text: str) -> str:
    """One line, so an assertion is not a claim about where it wraps."""
    return " ".join(text.split())


def a_session(task: str, repo: Path) -> Session:
    return Session(repo, task, [], policy=of(FAST), stop_after="straight")


# --------------------------------------------------------------------------
# 1. The look the policy had already asked for
# --------------------------------------------------------------------------


class TestTheStraightItemSaysWhetherAnybodyLooks:
    def test_it_is_set_from_the_same_signal_the_planned_path_uses(self):
        source = inspect.getsource(session.Session._work)
        assert "worth_looking_at=self._has_a_face()," in source

    def test_it_is_set_on_the_item_rather_than_by_widening_a_rule(self):
        """The fix is the item answering for itself. `_worth_a_look` is
        untouched, so an item that renders nothing still gets nothing."""
        source = inspect.getsource(orchestrate._worth_a_look)
        assert "item.worth_looking_at" in source
        assert "SEEN.search(name) for name in item.files" in source

    def test_a_website_has_a_face(self, tmp_path):
        s = a_session("Build a website for a hotel called AURA", tmp_path)
        assert s._has_a_face() is True

    def test_a_migration_does_not(self, tmp_path):
        s = a_session("Migrate the ledger table to the new schema", tmp_path)
        assert s._has_a_face() is False

    def test_an_item_with_no_files_used_to_answer_no(self):
        """The straight item carries no files, which is the whole of why
        this was broken: `any()` over an empty list is False."""
        blind = Item(id=1, title="t", rationale="r", files=[], verify_with="build")
        assert orchestrate._worth_a_look(blind) is False

    def test_and_now_answers_from_what_it_was_told(self):
        seen = Item(
            id=1,
            title="t",
            rationale="r",
            files=[],
            verify_with="build",
            worth_looking_at=True,
        )
        assert orchestrate._worth_a_look(seen) is True

    def test_a_straight_item_that_renders_nothing_is_still_not_looked_at(self):
        unseen = Item(
            id=1,
            title="t",
            rationale="r",
            files=[],
            verify_with="build",
            worth_looking_at=False,
        )
        assert orchestrate._worth_a_look(unseen) is False

    def test_fast_wanted_two_looks_all_along(self):
        assert of(FAST).self_looks == 2


class TestTheToolRestrictionsAreUnchanged:
    def test_looking_still_adds_only_the_look_command(self):
        from drydock.engines import LOOK, _shell_rule

        fenced = _shell_rule("npm run build", can_look=False)
        looking = _shell_rule("npm run build", can_look=True)
        assert looking == f"{fenced} Bash({LOOK}) Bash({LOOK} *)"

    def test_the_build_tool_is_still_the_only_other_thing(self):
        from drydock.engines import _shell_rule

        said = _shell_rule("npm run build", can_look=True)
        assert "Bash(npm *)" in said
        for forbidden in ("curl", "wget", "Bash(*)", "WebFetch", "WebSearch"):
            assert forbidden not in said

    def test_the_look_command_was_already_allowed(self):
        from drydock.confine import ALLOWED

        assert "drydock-look" in ALLOWED
        assert "curl" not in ALLOWED
        assert "wget" not in ALLOWED


# --------------------------------------------------------------------------
# 2. The design sections reach whoever does the designing
# --------------------------------------------------------------------------


class TestABriefingCanServeAStationThatDoesTwoJobs:
    def _skill(self, **sections) -> Skill:
        return Skill(
            name="s", description="d", path=Path("/x"), sections=dict(sections)
        )

    def test_one_role_still_works(self):
        said = briefing([self._skill(plan="PLANPART")], "plan")
        assert "PLANPART" in said

    def test_two_roles_come_back_together(self):
        said = briefing(
            [self._skill(plan="PLANPART", design="DESIGNPART")], "plan", "design"
        )
        assert "PLANPART" in said and "DESIGNPART" in said

    def test_the_preamble_is_sent_once(self):
        """It is the larger half of a short briefing, and asking twice
        used to send it twice."""
        said = briefing([self._skill(plan="P", design="D")], "plan", "design")
        assert said.count("packaged knowledge about this kind of work") == 1

    def test_a_role_the_skill_has_nothing_for_adds_nothing(self):
        said = briefing([self._skill(plan="P")], "plan", "design")
        assert said.count("From the skill") == 1

    def test_no_roles_at_all_is_empty(self):
        assert briefing([self._skill(plan="P")]) == ""

    def test_the_ranking_still_says_the_request_wins(self):
        said = briefing([self._skill(plan="P", design="D")], "plan", "design")
        assert "What the person asked for comes first" in flat(said)


class TestTheMergedStationReadsTheDesignSection:
    def test_it_asks_for_both(self):
        source = inspect.getsource(start.begin)
        assert 'briefing(skills or [], "plan", "design")' in source

    def test_the_designer_is_not_the_only_reader_any_more(self):
        """Before this, `briefing(..., "design")` appeared twice and both
        were in designer.py - and the one that is reached by default draws
        a logo."""
        readers = set()
        for name in ("start", "planner", "designer", "engineer", "analyst"):
            source = Path(f"src/drydock/{name}.py").read_text()
            if '"design"' in source and "briefing(" in source:
                for line in source.splitlines():
                    if "briefing(" in line and '"design"' in line:
                        readers.add(name)
        assert "start" in readers

    def test_the_planner_sends_its_preamble_once_too(self):
        source = Path("src/drydock/planner.py").read_text()
        assert 'briefing(chosen, "plan", "verify")' in source
        assert 'briefing(chosen, "verify")' not in source


class TestTheEngineerIsToldAboutPictures:
    def _engineer_section(self) -> str:
        for sk in discover(Path("skills")):
            if sk.name == "web-design":
                return flat((load(sk).sections or {})["engineer"])
        raise AssertionError("web-design is not installed")

    def test_it_says_what_may_not_be_done(self):
        said = self._engineer_section()
        assert "Nothing here can take, buy or generate a photograph" in said

    def test_inventing_the_file_is_the_only_thing_ruled_out(self):
        said = self._engineer_section()
        assert "That rules out inventing the file and nothing else" in said

    def test_it_says_supplied_images_may_be_used(self):
        said = self._engineer_section()
        assert "Images the request, the direction or the repository supplies" in said

    def test_it_says_how_to_hang_one_without_the_page_jumping(self):
        said = self._engineer_section()
        for detail in ("aspect ratio", 'loading="lazy"', "real `alt`"):
            assert detail in said

    def test_it_knows_the_mark_may_already_be_there(self):
        assert "`brand/logo.svg`" in self._engineer_section()

    def test_it_is_told_not_to_go_looking(self):
        """Measured before the rule existed: two workers spent a hundred
        and fifty minutes between them trying to prove a photograph was
        real."""
        said = self._engineer_section()
        assert "Do not go looking: there is no network here" in said

    def test_no_images_is_not_presented_as_the_rule(self):
        said = self._engineer_section()
        assert '"no pictures" is a decision about this page, not a rule' in said

    def test_it_does_not_restate_the_whole_design_section(self):
        """The long reasoning stays where the directing is done. This is a
        short operational list for whoever writes the markup."""
        for sk in discover(Path("skills")):
            if sk.name == "web-design":
                sections = load(sk).sections or {}
        assert len(sections["engineer"]) < len(sections["design"]) * 3
        assert "Type is most of it" not in sections["engineer"]


# --------------------------------------------------------------------------
# 3. An undirected visual item directs itself
# --------------------------------------------------------------------------


class TestTheEngineerDirectsItselfWhenNobodyElseDid:
    def test_there_is_something_to_say(self):
        assert hasattr(engineer, "DIRECT_YOURSELF")

    def test_it_is_used_only_when_there_is_no_direction(self):
        source = inspect.getsource(engineer.work)
        assert "if can_look and not direction.strip():" in source
        assert "direction = DIRECT_YOURSELF" in source

    def test_a_direction_that_exists_wins(self):
        """The planned path carries 4,515 characters of it. Nothing here
        may overwrite that."""
        source = flat(inspect.getsource(engineer.work))
        at = source.index("if can_look and not direction.strip():")
        assert "not direction.strip()" in source[at : at + 80]

    def test_it_is_decided_before_the_prompt_is_built(self):
        source = inspect.getsource(engineer.work)
        assert source.index("direction = DIRECT_YOURSELF") < source.index(
            'briefing(skills or [], "engineer")'
        )

    def test_a_job_nobody_looks_at_gets_no_palette(self):
        source = inspect.getsource(engineer.work)
        assert "if can_look and not direction.strip():" in source

    def test_it_asks_for_the_four_things_a_page_is_carried_by(self):
        said = flat(engineer.DIRECT_YOURSELF)
        assert "Who walks in" in said
        assert "The one gesture the page is carried by" in said
        assert "The ground, the ink and the one accent" in said
        assert "What the generic version of this page would be" in said

    def test_it_is_four_or_five_lines_and_not_a_plan(self):
        said = flat(engineer.DIRECT_YOURSELF)
        assert "in four or five lines" in said

    def test_it_does_not_become_an_acceptance_criterion(self):
        """The standing rule: a suggestion must not silently become a
        requirement that something else judges the work against."""
        said = flat(engineer.DIRECT_YOURSELF)
        assert "nothing downstream judges the result against it" in said
        assert "it is not an acceptance criterion, it does not become a test" in said

    def test_it_does_not_widen_the_item(self):
        said = flat(engineer.DIRECT_YOURSELF)
        assert "does not widen the item" in said
        assert "The item is still the whole of what you touch" in said

    def test_the_request_still_outranks_it(self):
        said = flat(engineer.DIRECT_YOURSELF)
        assert (
            "If the request or the brief already says one of these, that wins" in said
        )

    def test_no_second_worker_is_started_for_it(self):
        """It happens inside the turn the engineer already has. A station
        would cost another spawn and another minute."""
        source = inspect.getsource(engineer.work)
        for spawning in ("ClaudeCodeEngine(", "pool.submit", "ThreadPoolExecutor"):
            assert source.count(spawning) <= 1


# --------------------------------------------------------------------------
# What must not have moved
# --------------------------------------------------------------------------


class TestNothingAboutTheGatesChanged:
    def test_the_engineer_still_does_not_count_as_a_look(self):
        said = flat(engineer.LOOKING)
        assert "This is not a check that counts" in said
        assert "looked at by somebody who is not you" in said

    def test_the_four_gates_are_still_the_four_gates(self):
        assert orchestrate.GATES == ("verifier", "inspector", "reviewer", "critic")

    def test_a_dangerous_sentence_still_cannot_take_the_straight_path(self):
        source = inspect.getsource(session.Session._work)
        assert 'if self.stop_after == "straight" and self.floor:' in source
        assert 'self.stop_after = "planner"' in source

    def test_the_straight_path_still_runs_the_baseline_first(self):
        s = Session(Path("/x"), "build a page", [], stop_after="straight")
        assert s._stages() == ["baseline", "engineer"]

    def test_an_unapproved_plan_still_waits(self):
        source = inspect.getsource(session.Session._after_plan)
        assert "if auto_run:" in source
        assert "self.waiting = True" in source
        assert 'self.feed.emit("awaiting.approval")' in source
