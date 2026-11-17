"""The skills format is a contract with whoever writes a skill, so it is tested."""

from pathlib import Path

import pytest

from drydock.skills import briefing, discover, load

SKILLS = Path("skills")


@pytest.fixture
def installed():
    return discover(SKILLS)


class TestDiscovery:
    def test_finds_the_installed_skills(self, installed):
        assert {s.name for s in installed} >= {"junit4-to-junit5", "greenfield-service"}

    def test_frontmatter_only_until_chosen(self, installed):
        """Progressive disclosure is the point: a hundred skills cost nothing
        until one is used, and that only holds if discovery leaves the body alone."""
        assert all(not s.loaded for s in installed)
        assert all(s.description for s in installed)

    def test_body_arrives_when_loaded(self, installed):
        skill = load(next(s for s in installed if s.name == "junit4-to-junit5"))
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
        assert "junit4-to-junit5" in text

    def test_briefing_says_the_repository_wins(self, installed):
        """A skill is prior knowledge, not an override. If an agent trusts the
        skill over what it reads, a skill that is slightly out of date turns
        into a confident wrong answer."""
        assert "the repository wins" in briefing([load(installed[0])], "survey")


class TestApplicability:
    def test_a_java_skill_fits_a_java_repo(self, installed):
        skill = next(s for s in installed if s.name == "junit4-to-junit5")
        assert skill.fits("Java", "Maven")
        assert not skill.fits("Python", "uv")

    def test_a_skill_without_targets_fits_anything(self, installed):
        skill = next(s for s in installed if s.name == "dependency-upgrade")
        assert skill.fits("Python", "uv")
        assert skill.fits("Java", "Gradle")
