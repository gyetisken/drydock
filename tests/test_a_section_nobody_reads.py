"""Four skills had a section delivered to nobody, and nothing said so.

Measured before this: greenfield's `## Checked against what is current` -
7,704 characters of researched CSS guidance with sources - reached no
station at all, because its heading matched no role and the loader
dropped it without a word. Every skill's `## Survey` and `## Verify`
reached nobody either: the merged start reads `plan`, the engineer reads
`engineer`, the mark drawer reads `design`, and the two stations that
ask for the other roles only run when DRYDOCK_FOUR_STATIONS is set.

5,160 characters of that, plus 7,704 of this, written and never read.

The loader still understands every role, so a skill written for the
four-station path loads exactly as it did. What changed is that it says
what will not be read, by name and by size, instead of discarding it in
silence.
"""

import re
from pathlib import Path

import pytest

from drydock.skills import ASKED_FOR, SECTIONS, Skill, briefing, discover, load

ROOT = Path("skills").resolve()


def skills() -> list[Skill]:
    return [load(s) for s in sorted(discover(ROOT), key=lambda s: s.name)]


def flat(text: str) -> str:
    return " ".join(text.split())


def a_skill(tmp_path: Path, body: str) -> Skill:
    where = tmp_path / "made-up"
    where.mkdir()
    (where / "SKILL.md").write_text(
        "---\nname: made-up\ndescription: a skill\n---\n\n" + body
    )
    return load(next(s for s in discover(tmp_path) if s.name == "made-up"))


class TestNothingIsDroppedInSilence:
    def test_a_heading_that_names_no_role_is_reported(self, tmp_path):
        made = a_skill(tmp_path, "## Notes on colour\n\nsomething useful\n")
        assert made.unread
        head, why = made.unread[0]
        assert head == "Notes on colour"
        assert "names no station" in why
        assert "16 characters" in why

    def test_the_complaint_names_the_skill_and_the_fix(self, tmp_path):
        made = a_skill(tmp_path, "## Notes\n\nx\n")
        said = made.complaints()[0]
        assert said.startswith("made-up: `## Notes`")
        for role in SECTIONS:
            assert role in said

    def test_a_role_nobody_asks_for_is_reported_too(self, tmp_path):
        made = a_skill(tmp_path, "## Verify\n\nrun the suite\n")
        assert made.unread
        assert "DRYDOCK_FOUR_STATIONS" in made.unread[0][1]

    def test_it_is_still_loaded_rather_than_refused(self, tmp_path):
        """Compatibility: a skill written for the four-station path has
        to keep working, so the section is kept and merely announced."""
        made = a_skill(tmp_path, "## Verify\n\nrun the suite\n")
        assert made.guidance("verify") == "run the suite"

    def test_a_section_that_is_read_is_not_complained_about(self, tmp_path):
        made = a_skill(tmp_path, "## Engineer\n\nmind the gap\n")
        assert made.unread == ()
        assert made.guidance("engineer") == "mind the gap"

    def test_loose_headings_still_match(self, tmp_path):
        """ "## Engineer notes" was always allowed and still is."""
        made = a_skill(tmp_path, "## Engineer notes\n\nmind the gap\n")
        assert made.guidance("engineer") == "mind the gap"
        assert made.unread == ()

    def test_it_is_said_out_loud_when_a_skill_is_loaded(self, tmp_path, capsys):
        a_skill(tmp_path, "## Notes\n\nx\n")
        assert "skill: made-up: `## Notes`" in capsys.readouterr().err

    def test_a_clean_skill_says_nothing(self, tmp_path, capsys):
        a_skill(tmp_path, "## Plan\n\nx\n")
        assert capsys.readouterr().err == ""


class TestEveryInstalledSkillIsFullyDelivered:
    def test_none_of_them_has_an_unread_section(self):
        left = [said for s in skills() for said in s.complaints()]
        assert left == [], left

    def test_the_roles_they_use_are_roles_somebody_asks_for(self):
        for s in skills():
            for role in s.sections or {}:
                assert role in ASKED_FOR, f"{s.name}/{role}"

    def test_the_currency_block_is_gone_from_greenfield(self):
        said = (ROOT / "greenfield" / "SKILL.md").read_text()
        assert "## Checked against what is current" not in said

    def test_what_was_worth_keeping_from_it_is_in_web_design(self):
        """Seven findings, not seven thousand characters. The rest was
        either already said there, a dated claim, or a statistic
        nobody acts on."""
        said = flat(load_web().guidance("engineer"))
        for kept in (
            "color-scheme: light dark",
            "oklch()",
            "Firefox has not shipped it",
            ":focus-visible",
            "prefers-reduced-motion",
            "anchor positioning",
        ):
            assert kept in said, kept

    def test_the_dated_claims_did_not_come_with_it(self):
        said = flat(load_web().guidance("engineer"))
        for stale in ("2026-11-13", "four days before today", "Baseline Newly"):
            assert stale not in said, stale

    def test_the_statistics_did_not_come_with_it(self):
        said = flat(load_web().guidance("engineer"))
        for stat in ("67%", "39.4%", "httparchive", "European Accessibility Act"):
            assert stat not in said, stat


def load_web() -> Skill:
    return next(s for s in skills() if s.name == "web-design")


class TestThePhotographyGuidanceIsConditional:
    def said(self) -> str:
        return flat(load_web().guidance("design"))

    def test_the_malformed_heading_is_gone(self):
        raw = (ROOT / "web-design" / "SKILL.md").read_text()
        assert not [line for line in raw.splitlines() if line.startswith("** ")]

    def test_neither_path_is_forced(self):
        said = self.said()
        assert "Which of the two remaining paths is right depends on what you" in said
        assert "*If the request, the direction or the repository supplies" in said
        assert "*If nothing supplies them*" in said

    def test_the_one_real_prohibition_survives(self):
        said = self.said()
        assert "a file of flat colour named `.jpg` is a lie that passes a build" in said
        assert "rules out one thing and one thing only: inventing the image file" in (
            said
        )

    def test_it_no_longer_names_one_source_as_the_answer(self):
        assert "Unsplash serves them directly" not in self.said()

    def test_the_advice_for_images_that_do_exist_is_kept(self):
        said = self.said()
        for kept in ("aspect ratio", 'loading="lazy"', "a real `alt`"):
            assert kept in said, kept

    def test_the_network_warning_is_kept(self):
        said = self.said()
        assert "this process has no network" in said
        assert "a hundred and fifty minutes" in said


class TestThePlannerGetsADirectionNotAStylesheet:
    def test_web_design_now_speaks_to_the_planner(self):
        assert load_web().guidance("plan")

    def test_it_is_not_a_copy_of_the_design_section(self):
        web = load_web()
        plan, design = web.guidance("plan"), web.guidance("design")
        assert len(plan) < len(design)
        assert plan not in design
        # Different words for different jobs, not an excerpt.
        assert "One gesture" in design and "Name the one gesture" in plan

    def test_it_says_what_the_planner_decides(self):
        said = flat(load_web().guidance("plan"))
        for kept in (
            "Direct for this business, not for businesses",
            "Name the one gesture",
            "Say what the generic version would be",
            "Say what pictures are available, and leave the rest open",
            "Intent, not values",
            "read on a phone, standing up",
        ):
            assert kept in said, kept

    def test_it_sends_the_building_to_the_engineer(self):
        said = flat(load_web().guidance("plan"))
        assert "The whole of how to build a page is under `## Engineer`" in said

    def test_it_does_not_prescribe_values(self):
        said = flat(load_web().guidance("plan"))
        assert "leave the hex, the type scale, the spacing" in said
        for typing in ("clamp(", "oklch(", "light-dark(", "grid-column"):
            assert typing not in said, typing


STATIONS = (
    ("plan", "src/drydock/start.py"),
    ("engineer", "src/drydock/engineer.py"),
    ("design", "src/drydock/designer.py"),
)


class TestWhatEachStationNowReceives:
    @pytest.mark.parametrize(("role", "where"), STATIONS)
    def test_the_station_asks_for_it(self, role, where):
        """Asked for, alone or beside another role. `start.py` reads,
        directs and plans in one call, so it takes `"plan", "design"` -
        and insisting on the single-role spelling would have made the
        only fix for a section nobody read look like a regression."""
        said = Path(where).read_text()
        asked = re.findall(r"briefing\(\s*skills(?: or \[\])?\s*,([^)]*)\)", said)
        assert any(f'"{role}"' in call for call in asked), asked

    def test_the_merged_start_is_the_default_path(self):
        said = Path("src/drydock/session.py").read_text()
        assert 'os.environ.get("DRYDOCK_FOUR_STATIONS") != "1"' in said

    def test_nothing_reaches_the_deterministic_stations(self):
        """The verifier and the inspector run commands and read a diff.
        Prose cannot help either of them."""
        for where in ("src/drydock/verify.py", "src/drydock/inspect.py"):
            assert "briefing(" not in Path(where).read_text(), where


class TestASkillStillCannotOutrankTheRequest:
    def said(self) -> str:
        return flat(briefing(skills(), "engineer"))

    def test_the_ranking_is_still_stated(self):
        said = self.said()
        assert "What the person asked for comes first and is never overridden" in said
        assert "This block is last" in said

    def test_it_still_may_not_add_a_requirement(self):
        assert (
            "may not add an item, a feature or a requirement that the person "
            "did not ask for" in self.said()
        )

    def test_a_disagreement_is_still_reported(self):
        assert "say in your answer that the two disagreed" in self.said()

    def test_no_skills_is_still_no_preamble(self):
        assert briefing([], "engineer") == ""


class TestPromptSize:
    """Recorded rather than capped. A number in a test is how a change
    that doubles a prompt gets noticed instead of discovered later."""

    PAIR = ("greenfield", "web-design")

    def pair(self) -> list[Skill]:
        return [s for s in skills() if s.name in self.PAIR]

    def test_the_planner_briefing_stays_small(self):
        said = briefing(self.pair(), "plan")
        assert len(said) < 6000, len(said)

    def test_the_engineer_briefing_stays_under_what_it_was(self):
        """It was 7,817 for this pair before the folding, and the folding
        moved content into it. The bound exists because the engineer's
        own instructions are 5,157 and a skill should not swamp its host.

        Raised once, from 10,500, and the reason is on the record rather
        than in a commit message. A benchmark ran the same sentence four
        times: two runs under this skill produced nought and two SVGs
        between them, two runs without it produced nine and thirteen, and
        three blind judges each named the absence of any image as the
        first thing wrong with ours. What was missing was one clause -
        the skill told the engineer what it could not photograph and
        never told it that it could draw - and that clause had been cut
        from this same passage to fit this same number. Trimming the
        craft guidance to make room for it would have been the same
        mistake twice, so the number moved instead.

        It is still a bound and it is still enforced. If it has to move
        again, something in here is not earning its place."""
        said = briefing(self.pair(), "engineer")
        assert len(said) < 11600, len(said)

    def test_no_skill_file_is_mostly_undelivered(self):
        for s in skills():
            whole = len((s.path / "SKILL.md").read_text())
            live = sum(len(s.guidance(r)) for r in ASKED_FOR)
            assert live > whole * 0.7, f"{s.name}: {live} of {whole}"


class TestTheExistingWorkflowsAreIntact:
    def test_every_skill_still_has_frontmatter_that_loads(self):
        for s in skills():
            assert s.name and s.description

    def test_the_commands_still_exist(self):
        by_name = {s.name: s for s in skills()}
        assert by_name["greenfield"].command == "/new"
        assert by_name["migration"].command == "/migrate"
        assert by_name["dependency-upgrade"].command == "/upgrade"

    def test_web_design_is_still_the_one_without_a_command(self):
        """It is brought in by what the job looks like, not by typing."""
        assert load_web().command == ""
        assert '_bring_in("web-design"' in Path("src/drydock/session.py").read_text()

    def test_the_greenfield_task_template_is_unchanged(self):
        said = next(s for s in skills() if s.name == "greenfield").task
        assert said.startswith("Build {what}.")

    def test_the_engineer_guidance_each_skill_still_has(self):
        for s in skills():
            assert s.guidance("engineer"), s.name
