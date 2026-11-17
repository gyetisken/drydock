"""Reading the working tree.

The review diff exists separately from the commit diff for one reason: a
lockfile of two thousand lines is in the commit and must not be in the
review, where it pushes the three files somebody actually wrote out of the
window entirely.
"""

import subprocess
from pathlib import Path

from drydock.repo import Repo


def make(tmp_path: Path) -> Repo:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "start"],
        cwd=tmp_path,
        check=True,
    )
    return Repo(tmp_path)


def test_the_review_diff_leaves_out_what_nobody_wrote(tmp_path):
    repo = make(tmp_path)
    (tmp_path / "app.js").write_text("export const x = 1;\n")
    (tmp_path / "package-lock.json").write_text("{\n" + '  "x": 1,\n' * 400 + "}\n")

    full = repo.pending()
    lean = repo.pending_for_review()

    assert "app.js" in full and "app.js" in lean
    assert "package-lock.json" in full
    assert "package-lock.json" not in lean
    assert len(lean) < len(full) / 5


def test_every_lockfile_this_knows_about_is_left_out(tmp_path):
    repo = make(tmp_path)
    for name in ("yarn.lock", "poetry.lock", "uv.lock", "go.sum", "Cargo.lock"):
        (tmp_path / name).write_text("generated\n")
    (tmp_path / "real.py").write_text("x = 1\n")

    lean = repo.pending_for_review()
    assert "real.py" in lean
    for name in ("yarn.lock", "poetry.lock", "uv.lock", "go.sum", "Cargo.lock"):
        assert name not in lean, name


def test_a_clean_tree_has_nothing_pending(tmp_path):
    assert make(tmp_path).pending_for_review().strip() == ""


def test_drydock_cleans_up_after_itself(tmp_path):
    """The preview log dirtied a repository and stopped the next job in it,
    which is the thing this program refuses to let the crew do."""
    repo = make(tmp_path)
    (tmp_path / ".drydock-preview.log").write_text("noise\n")
    (tmp_path / ".drydock-report.json").write_text("{}\n")
    (tmp_path / "real.js").write_text("export const x = 1;\n")

    gone = repo.sweep()

    assert set(gone) == {".drydock-preview.log", ".drydock-report.json"}
    assert (tmp_path / "real.js").exists()
    assert not (tmp_path / ".drydock-preview.log").exists()


def test_sweeping_a_clean_repository_removes_nothing(tmp_path):
    assert make(tmp_path).sweep() == []


class TestWhereASecondWorkingCopyGoes:
    """Beside the repository is the wrong place. The parent of a repository
    is usually the folder holding every other one somebody owns, and a run
    that is killed leaves its working copies behind - so drydock's debris
    ends up among their projects."""

    def test_it_is_under_drydock_s_own_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = _a_repo(tmp_path / "nero")

        where = repo.worktree("item2", repo.head())
        try:
            assert (tmp_path / "home" / "worktrees") in where.parents
            assert where.name == "nero-item2"
        finally:
            repo.drop_worktree(where)

    def test_nothing_is_left_beside_the_repository(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = _a_repo(tmp_path / "nero")

        where = repo.worktree("item1", repo.head())
        try:
            assert not list(tmp_path.glob(".drydock-*"))
        finally:
            repo.drop_worktree(where)

    def test_two_items_get_two_copies(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = _a_repo(tmp_path / "nero")

        one = repo.worktree("item1", repo.head())
        two = repo.worktree("item2", repo.head())
        try:
            assert one != two
            assert one.exists() and two.exists()
        finally:
            repo.drop_worktree(one)
            repo.drop_worktree(two)


def _a_repo(where):
    """A repository with one commit, which is the least a worktree needs."""
    import subprocess

    from drydock.repo import Repo

    where.mkdir(parents=True)

    def sh(command: str) -> None:
        subprocess.run(command, cwd=where, shell=True, capture_output=True, check=True)

    sh("git init -q && git config user.email t@t && git config user.name t")
    (where / "README.md").write_text("nero\n")
    sh("git add -A && git commit -q -m first")
    return Repo(where)


class TestWhatASecondWorkingCopyIsLent:
    """git carries what it tracks, and a project's dependencies are the
    thing it deliberately does not track. So the first thing a worker did
    in a worktree was install the entire tree again - minutes of it, per
    item - and four items working at once meant four installs of the same
    thing."""

    def test_node_modules_is_lent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = _a_repo(tmp_path / "nero")
        (repo.path / "node_modules" / "vitest").mkdir(parents=True)

        where = repo.worktree("item1", repo.head())
        try:
            assert (where / "node_modules").is_symlink()
            assert (where / "node_modules" / "vitest").is_dir()
        finally:
            repo.drop_worktree(where)

    def test_a_python_environment_is_lent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = _a_repo(tmp_path / "svc")
        (repo.path / ".venv" / "bin").mkdir(parents=True)

        where = repo.worktree("item1", repo.head())
        try:
            assert (where / ".venv").is_symlink()
        finally:
            repo.drop_worktree(where)

    def test_what_the_project_does_not_have_is_not_invented(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = _a_repo(tmp_path / "plain")

        where = repo.worktree("item1", repo.head())
        try:
            assert not (where / "node_modules").exists()
        finally:
            repo.drop_worktree(where)

    def test_it_is_lent_not_copied(self, tmp_path, monkeypatch):
        """A copy of a dependency tree is slower than installing one."""
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = _a_repo(tmp_path / "nero")
        (repo.path / "node_modules").mkdir()

        where = repo.worktree("item1", repo.head())
        try:
            assert (where / "node_modules").resolve() == (
                repo.path / "node_modules"
            ).resolve()
        finally:
            repo.drop_worktree(where)

    def test_dropping_the_copy_leaves_the_original(self, tmp_path, monkeypatch):
        """Removing a worktree must not take the project's dependencies
        with it."""
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        repo = _a_repo(tmp_path / "nero")
        (repo.path / "node_modules" / "vitest").mkdir(parents=True)

        where = repo.worktree("item1", repo.head())
        repo.drop_worktree(where)

        assert (repo.path / "node_modules" / "vitest").is_dir()
