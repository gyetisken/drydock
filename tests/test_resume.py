"""Carrying on a job that stopped.

A run here takes twenty minutes and the thread it runs on does not survive
the application closing, a crash, or somebody restarting the server. The
record on disk does survive all three, and each item is its own commit, so
the work that landed is still landed. What has to hold is that the second
half of a plan is worked under the same conditions as the first - and the
failure mode is quiet, because a resumed run that is subtly worse still
looks like a resumed run.
"""

from pathlib import Path

import pytest

from drydock.session import _skills_named


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """Two skills on disk, in the place the loader looks."""
    root = tmp_path / "skills"
    for name, engineer in (
        ("greenfield", "Tests from the first commit."),
        ("web-design", "Test the data, not the rendering."),
    ):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: a skill\n---\n\n"
            f"# {name}\n\n## Engineer\n\n{engineer}\n"
        )
    monkeypatch.chdir(tmp_path)
    return root


class TestTheSkillsComeBack:
    def test_the_skills_the_run_recorded_are_loaded(self, installed):
        """The bug: this was an empty list, so the engineer worked the rest
        of the plan without the knowledge the first half had."""
        back = _skills_named(["greenfield", "web-design"])
        assert [s.name for s in back] == ["greenfield", "web-design"]

    def test_they_come_back_with_their_bodies_read(self, installed):
        """A skill loaded by name only is a name. What the engineer needs is
        the section written for the engineer."""
        back = _skills_named(["web-design"])
        assert "Test the data" in back[0].guidance("engineer")

    def test_they_are_read_as_they_are_now(self, installed):
        """A skill corrected after a run stopped is the usual reason to
        resume it, so the correction has to apply."""
        (installed / "web-design" / "SKILL.md").write_text(
            "---\nname: web-design\ndescription: a skill\n---\n\n"
            "# web-design\n\n## Engineer\n\nThe corrected rule.\n"
        )
        back = _skills_named(["web-design"])
        assert "The corrected rule" in back[0].guidance("engineer")

    def test_a_skill_that_has_since_been_uninstalled_is_skipped(self, installed):
        """Not fatal. A run under a skill nobody has any more is still a run
        that can finish."""
        back = _skills_named(["greenfield", "deleted-skill"])
        assert [s.name for s in back] == ["greenfield"]

    def test_no_skills_recorded_means_no_skills(self, installed):
        assert _skills_named([]) == []

    def test_nothing_installed_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _skills_named(["greenfield"]) == []
