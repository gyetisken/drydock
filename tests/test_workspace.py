"""The list of projects, and the things somebody chose about them.

A name, a pin and a standing instruction are all decisions a person made
about a folder, and none of them exist anywhere else - unlike the
repository, which is its own record. Writing them down was a hand-written
list of three fields that did not include any of them, so all three were
kept for exactly as long as the application stayed open. That looks
identical to a feature that does not work.
"""

from datetime import datetime
from pathlib import Path

import pytest

from drydock.workspace import Project, Workspace, _home


@pytest.fixture
def home(tmp_path, monkeypatch):
    """The list is written to a fixed place, so it has to be moved."""
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path))
    return tmp_path


def a_workspace(home: Path, *projects: Project) -> Workspace:
    space = Workspace()
    space.projects = list(projects)
    return space


def a_project(where: str = "/tmp/nero", **kw) -> Project:
    return Project(Path(where), datetime.now().strftime("%Y-%m-%d %H:%M"), **kw)


def reopened(space: Workspace) -> Workspace:
    """What the application sees the next time it starts."""
    return Workspace().load()


class TestWhatSurvivesBeingClosed:
    def test_a_name_somebody_chose(self, home):
        space = a_workspace(home, a_project())
        space.rename("/tmp/nero", "Nero")

        assert reopened(space).projects[0].label == "Nero"

    def test_a_pin(self, home):
        space = a_workspace(home, a_project())
        space.pin("/tmp/nero", True)

        assert reopened(space).projects[0].pinned is True

    def test_a_standing_instruction(self, home):
        """The thing somebody would otherwise retype at the end of every
        command. Losing it means retyping it, which means not using it."""
        space = a_workspace(home, a_project())
        space.instruct("/tmp/nero", "Never touch the migrations folder.")

        assert "migrations" in reopened(space).projects[0].instructions

    def test_everything_at_once(self, home):
        space = a_workspace(home, a_project())
        space.rename("/tmp/nero", "Nero")
        space.pin("/tmp/nero", True)
        space.instruct("/tmp/nero", "Always TypeScript.")
        space.touch(Path("/tmp/nero"))

        back = reopened(space).projects[0]
        assert back.label == "Nero"
        assert back.pinned
        assert back.instructions == "Always TypeScript."
        assert back.last_used


class TestTheOrder:
    def test_pinned_first(self, home):
        space = a_workspace(home, a_project("/tmp/a"), a_project("/tmp/b"))
        space.pin("/tmp/b", True)

        assert [str(p.path) for p in space.projects] == ["/tmp/b", "/tmp/a"]

    def test_then_whatever_was_used_most_recently(self, home):
        older = a_project("/tmp/a")
        older.last_used = "2026-11-01 09:00"
        newer = a_project("/tmp/b")
        newer.last_used = "2026-11-17 09:00"
        space = a_workspace(home, older, newer)
        space._order()

        assert [str(p.path) for p in space.projects] == ["/tmp/b", "/tmp/a"]

    def test_the_order_survives_being_closed(self, home):
        space = a_workspace(home, a_project("/tmp/a"), a_project("/tmp/b"))
        space.pin("/tmp/b", True)

        assert str(reopened(space).projects[0].path) == "/tmp/b"


class TestItNeverLosesTheList:
    def test_a_file_that_cannot_be_read_is_an_empty_list(self, home):
        """Not a crash on startup. The projects are recoverable by adding
        the folders again; a window that will not open is not."""
        space = a_workspace(home, a_project())
        space.save()
        space._file.write_text("{ not json")

        assert reopened(space).projects == []

    def test_an_entry_without_a_path_is_skipped(self, home):
        space = a_workspace(home)
        space._file.parent.mkdir(parents=True, exist_ok=True)
        space._file.write_text('[{"added": "2026-11-17 10:00"}, {"path": "/tmp/b"}]')

        assert [str(p.path) for p in reopened(space).projects] == ["/tmp/b"]

    def test_a_field_added_since_the_file_was_written_takes_its_default(self, home):
        space = a_workspace(home)
        space._file.parent.mkdir(parents=True, exist_ok=True)
        space._file.write_text('[{"path": "/tmp/nero", "added": "2026-11-17 10:00"}]')

        back = reopened(space).projects[0]
        assert back.label == ""
        assert back.pinned is False

    def test_forgetting_one_keeps_the_others(self, home):
        space = a_workspace(home, a_project("/tmp/a"), a_project("/tmp/b"))
        space.forget("/tmp/a")

        assert [str(p.path) for p in reopened(space).projects] == ["/tmp/b"]


def test_a_project_is_called_what_somebody_called_it():
    """A folder called `api-v2-final` can be called the thing it actually
    is, without renaming anything on disk."""
    assert a_project("/tmp/api-v2-final").name == "api-v2-final"
    assert a_project("/tmp/api-v2-final", label="Billing API").name == "Billing API"


def test_the_home_is_where_it_says_it_is(monkeypatch):
    monkeypatch.delenv("DRYDOCK_HOME", raising=False)
    assert _home().name == ".drydock"
    assert _home().parent == Path.home()


def test_the_home_can_be_moved_out_of_the_way(monkeypatch, tmp_path):
    """The whole of `conftest` rests on this. It was a module constant
    read once at import, so the suite ignored `DRYDOCK_HOME` entirely
    and saved an empty project list over the real one - every time
    anybody ran it."""
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "elsewhere"))
    assert _home() == tmp_path / "elsewhere"

    kept = Workspace()
    kept.projects = [Project(Path("/tmp/a-project"), "2026-01-01")]
    kept.save()
    assert (tmp_path / "elsewhere" / "projects.json").exists()
    assert not (Path.home() / ".drydock" / "projects.json").samefile(
        tmp_path / "elsewhere" / "projects.json"
    )


def test_it_is_read_when_it_is_used_rather_than_at_import(monkeypatch, tmp_path):
    """A constant would have been fixed by whatever the environment was
    when the module happened to be imported, which is before any test
    has set anything."""
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "one"))
    first = Workspace()._file
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "two"))
    assert Workspace()._file != first
