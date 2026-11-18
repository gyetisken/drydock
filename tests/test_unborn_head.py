"""A repository that exists and has never been committed to.

`git init` and nothing else is a real repository with no HEAD at all, and
it is what somebody has after making a folder for a new project. Every
check in `repo.py` reads HEAD, so the first thing a run did with such a
folder was die on `git rev-parse --verify HEAD failed (exit 128)` -
before planning, before a worker, with nothing said that anybody could
act on.

Observed on a real attempt: a new `HealthApi` folder, `git init`, no
commit, and every `/new` against it ended there.

The folder-adding path had the fix and asked the wrong question for it -
it looked for `.git` and committed only when there was none, so a folder
that was already a repository skipped the first commit entirely. The CLI
never went through that path at all.
"""

import subprocess
from pathlib import Path

import pytest

from drydock.repo import GitError, Repo


def a_bare_init(tmp_path: Path) -> Repo:
    """A repository with no commits, which is the whole subject here."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return Repo(tmp_path)


def log(repo: Repo) -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.split()


class TestNoticingIt:
    def test_a_repository_with_no_commit_has_no_history(self, tmp_path):
        assert a_bare_init(tmp_path).has_history() is False

    def test_one_commit_is_history(self, tmp_path):
        repo = a_bare_init(tmp_path)
        repo.start_history()
        assert repo.has_history() is True


class TestGivingItAFirstCommit:
    def test_an_empty_folder_gets_one(self, tmp_path):
        repo = a_bare_init(tmp_path)
        repo.start_history()

        assert repo.has_history()
        assert repo.is_clean()
        assert log(repo) == ["before", "drydock"]

    def test_the_files_already_there_are_in_it(self, tmp_path):
        """Not left untracked. A tree with untracked files is not clean, and
        the run is refused for the wrong reason one line further down."""
        repo = a_bare_init(tmp_path)
        (tmp_path / "server.js").write_text("console.log(1)\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.js").write_text("export const x = 1\n")

        repo.start_history()

        assert repo.is_clean()
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert tracked == ["server.js", "src/app.js"]

    def test_a_repository_with_history_is_left_exactly_alone(self, tmp_path):
        """The important half. Where there is history, an uncommitted change
        is work somebody did, and folding it into a baseline commit without
        asking is the thing AGENTS.md forbids. The refusal further down
        still stands."""
        repo = a_bare_init(tmp_path)
        repo.start_history()
        (tmp_path / "half-finished.py").write_text("x = \n")

        repo.start_history()

        assert log(repo) == ["before", "drydock"]
        assert not repo.is_clean()

    def test_it_can_be_called_twice_without_adding_a_second_commit(self, tmp_path):
        repo = a_bare_init(tmp_path)
        repo.start_history()
        repo.start_history()
        assert log(repo) == ["before", "drydock"]


class TestWhatItSaysWhenItCannotCarryOn:
    def test_the_refusal_names_the_cause(self, tmp_path):
        """`require_checkout` is reached from eight places. If one of them
        ever meets a repository with no commits again, the message has to
        be the reason rather than a git exit code."""
        repo = a_bare_init(tmp_path)

        with pytest.raises(GitError) as raised:
            repo.require_checkout("drydock/20261118-000000")

        said = str(raised.value)
        assert "no commits yet" in said
        assert str(tmp_path) in said
        assert "exit 128" not in said


class TestBothWaysIn:
    """The folder-added-in-the-window path and the CLI path. Fixing only
    the first is what left this open: `drydock survey` never touches it."""

    def test_adding_a_commitless_repository_as_a_project_commits_it(
        self, tmp_path, monkeypatch
    ):
        from drydock.workspace import Workspace

        monkeypatch.setattr("drydock.workspace.HOME", tmp_path / "home")
        (tmp_path / "home").mkdir()
        project = tmp_path / "HealthApi"
        project.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=project, check=True)

        Workspace().add_project(project)

        assert Repo(project).has_history()

    def test_adding_a_plain_folder_still_works(self, tmp_path, monkeypatch):
        from drydock.workspace import Workspace

        monkeypatch.setattr("drydock.workspace.HOME", tmp_path / "home")
        (tmp_path / "home").mkdir()
        project = tmp_path / "Fresh"
        project.mkdir()

        Workspace().add_project(project)

        assert (project / ".git").is_dir()
        assert Repo(project).has_history()

    def test_the_run_path_commits_before_it_asks_for_a_clean_tree(self):
        """`execute` sweeps, then starts history, then checks cleanliness.
        That order matters in both directions: sweeping afterwards would
        commit drydock's own leftovers, and checking cleanliness first
        refuses a commitless repository for having untracked files."""
        source = (
            Path(__file__).resolve().parents[1] / "src" / "drydock" / "orchestrate.py"
        ).read_text()
        sweep = source.index("repo.sweep()")
        started = source.index("repo.start_history()", sweep)
        clean = source.index("if not repo.is_clean():", sweep)

        assert sweep < started < clean
