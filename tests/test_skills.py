"""The skills format is a contract with whoever writes a skill, so it is tested."""

from pathlib import Path

import pytest

from drydock.skills import Skill, briefing, discover, load

SKILLS = Path("skills")


@pytest.fixture
def installed():
    return discover(SKILLS)


class TestDiscovery:
    def test_finds_the_installed_skills(self, installed):
        assert {s.name for s in installed} >= {"migration", "greenfield"}

    def test_frontmatter_only_until_chosen(self, installed):
        """Progressive disclosure is the point: a hundred skills cost nothing
        until one is used, and that only holds if discovery leaves the body alone."""
        assert all(not s.loaded for s in installed)
        assert all(s.description for s in installed)

    def test_body_arrives_when_loaded(self, installed):
        skill = load(next(s for s in installed if s.name == "migration"))
        assert skill.loaded
        assert set(skill.sections) == {"survey", "plan", "engineer", "verify"}


class TestGuidance:
    def test_each_role_gets_its_own_section(self, installed):
        skill = load(installed[0])
        assert skill.guidance("survey") != skill.guidance("engineer")

    def test_a_role_with_nothing_to_say_says_nothing(self):
        skill = load(discover(SKILLS)[0])
        assert skill.guidance("reviewer") == ""

    def test_briefing_is_empty_without_skills(self):
        assert briefing([], "survey") == ""

    def test_briefing_names_its_source(self, installed):
        text = briefing([load(s) for s in installed], "plan")
        assert "migration" in text

    def test_briefing_ranks_the_skill_last(self, installed):
        """A skill is prior knowledge, not an override. If an agent
        trusts the skill over what it reads, a skill that is slightly
        out of date turns into a confident wrong answer - and if it
        trusts it over the request, a document written months ago for
        nobody in particular outranks the sentence somebody typed this
        morning. Both happened. See
        test_the_skill_does_not_outrank_the_request."""
        said = " ".join(briefing([load(installed[0])], "survey").split())
        assert "What the person asked for comes first" in said
        assert "This block is last" in said
        assert "a fact about this job where a skill is a generalisation" in said


class TestApplicability:
    def test_a_skill_that_names_targets_is_held_to_them(self):
        skill = Skill(
            name="x", description="", path=SKILLS, applies_to=("Java", "Maven")
        )
        assert skill.fits("Java", "Maven")
        assert not skill.fits("Python", "uv")

    def test_a_skill_without_targets_fits_anything(self, installed):
        skill = next(s for s in installed if s.name == "dependency-upgrade")
        assert skill.fits("Python", "uv")
        assert skill.fits("Java", "Gradle")

    def test_no_installed_skill_is_tied_to_one_language(self, installed):
        """The shipped skills describe a kind of work, not a stack. A skill
        that only fires on Java is a skill most repositories cannot use."""
        assert all(not s.applies_to for s in installed)
