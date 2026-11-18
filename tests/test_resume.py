"""Carrying on a job that stopped.

A run here takes twenty minutes and the thread it runs on does not survive
the application closing, a crash, or somebody restarting the server. The
record on disk does survive all three, and each item is its own commit, so
the work that landed is still landed. What has to hold is that the second
half of a plan is worked under the same conditions as the first - and the
failure mode is quiet, because a resumed run that is subtly worse still
looks like a resumed run.
"""

import subprocess

import pytest

from drydock import orchestrate
from drydock.models import Item, ItemResult, Outcome
from drydock.repo import GitError, Repo
from drydock.run import Run
from drydock.session import Session, _skills_named


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


def _git(repo, *args):
    done = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def _item(id=1):
    return Item(
        id=id,
        title=f"item {id}",
        rationale="because",
        files=["tracked.txt"],
        verify_with="build",
    )


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A real, isolated git checkout with a locally configured identity."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked.txt").write_text("v1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    monkeypatch.chdir(tmp_path)
    return repo


def _resumable_run(repo):
    """A run anchored on its own branch, ready to be resumed."""
    run = Run.start(repo, "do the thing")
    Repo(repo).branch(run.branch)
    run.anchor = _git(repo, "rev-parse", "HEAD")
    run.save()
    return run


class TestCleanResume:
    def test_clean_tree_resumes_without_touching_git(self, git_repo, monkeypatch):
        calls = []
        monkeypatch.setattr(Session, "approve", lambda self: calls.append(1))
        run = _resumable_run(git_repo)
        before = Repo(git_repo).head()

        session = Session.resume(run)

        assert calls == [1]
        assert session.run.id == run.id
        assert Repo(git_repo).head() == before

    def test_clean_resume_never_starts_a_real_worker(self, git_repo, monkeypatch):
        started = []
        monkeypatch.setattr(Session, "work_the_plan", lambda self: started.append(1))
        run = _resumable_run(git_repo)

        session = Session.resume(run)
        session._thread.join(timeout=2)

        assert started == [1]


class TestDirtyTreeRefusesResume:
    def test_staged_unstaged_and_untracked_block_resume(self, git_repo, monkeypatch):
        monkeypatch.setattr(Session, "approve", lambda self: None)
        run = _resumable_run(git_repo)

        tracked = git_repo / "tracked.txt"
        # staged
        tracked.write_text("staged change\n")
        _git(git_repo, "add", "tracked.txt")
        # unstaged, on top of the staged change to the same file
        tracked.write_text("unstaged change\n")
        # untracked
        (git_repo / "scratch.txt").write_text("new\n")

        status_before = _git(git_repo, "status", "--porcelain")
        run_bytes_before = run.path.read_bytes()
        head_before = _git(git_repo, "rev-parse", "HEAD")

        with pytest.raises(GitError, match="with changes"):
            Session.resume(run)

        assert _git(git_repo, "rev-parse", "HEAD") == head_before
        assert _git(git_repo, "status", "--porcelain") == status_before
        assert run.path.read_bytes() == run_bytes_before
        assert _git(git_repo, "show", ":tracked.txt") == "staged change"
        assert tracked.read_bytes() == b"unstaged change\n"
        assert (git_repo / "scratch.txt").read_bytes() == b"new\n"


class TestBranchMismatchRefusesResume:
    @pytest.mark.parametrize(
        "mutate",
        ["wrong_branch", "detached", "stale_tip", "missing_branch"],
    )
    def test_each_case_is_refused(self, git_repo, monkeypatch, mutate):
        monkeypatch.setattr(Session, "approve", lambda self: None)
        run = _resumable_run(git_repo)

        if mutate == "wrong_branch":
            _git(git_repo, "checkout", "-b", "somewhere-else")
        elif mutate == "detached":
            _git(git_repo, "checkout", "--detach")
        elif mutate == "stale_tip":
            (git_repo / "tracked.txt").write_text("v2\n")
            _git(git_repo, "add", "-A")
            _git(git_repo, "commit", "-q", "-m", "moved on")
        elif mutate == "missing_branch":
            _git(git_repo, "checkout", "main")
            _git(git_repo, "branch", "-D", run.branch)

        with pytest.raises(GitError):
            Session.resume(run)

    def test_nonzero_git_status_itself_is_refused(self, git_repo, monkeypatch):
        """A `git status` that fails outright is not the same as a clean
        tree, and must not be read as one."""
        monkeypatch.setattr(Session, "approve", lambda self: None)
        run = _resumable_run(git_repo)

        real_git = Repo._git

        def failing_status(self, args):
            if args.startswith("status"):
                return 128, "fatal: unable to read status"
            return real_git(self, args)

        monkeypatch.setattr(Repo, "_git", failing_status)

        with pytest.raises(GitError):
            Session.resume(run)


class TestInvalidationBeforeExecute:
    def test_a_branch_moved_after_resume_checked_is_still_refused(
        self, git_repo, monkeypatch
    ):
        """The check in Session.resume and the check inside execute are two
        separate gates. A branch that is fine when resume looks but has
        moved by the time execute runs must still be caught."""
        monkeypatch.setattr(Session, "approve", lambda self: None)
        run = _resumable_run(git_repo)
        Session.resume(run)  # passes: nothing has moved yet

        _git(git_repo, "commit", "--allow-empty", "-q", "-m", "moved on")

        with pytest.raises(GitError):
            orchestrate.execute(run)


class TestUnanchoredLegacyExecuteDoesNotMoveAnExistingBranch:
    """The blocker: a legacy `Run` with no anchor and an existing
    `drydock/<id>` branch used to be treated as brand new. It called sweep
    and `checkout -B`, which moves that branch off the commit it was last
    accepted at and onto whatever is currently checked out."""

    def test_branch_with_results_is_refused_before_any_mutation(self, git_repo):
        run = Run.start(git_repo, "do the thing")
        Repo(git_repo).branch(run.branch)
        _git(git_repo, "commit", "--allow-empty", "-q", "-m", "old accepted work")
        accepted_tip = _git(git_repo, "rev-parse", "HEAD")
        _git(git_repo, "checkout", "main")

        run.results = [
            ItemResult(item=_item(), outcome=Outcome.DONE, commit=accepted_tip)
        ]
        run.anchor = ""  # the legacy case: no anchor was ever recorded
        (git_repo / ".drydock-report.json").write_text("{}\n")

        with pytest.raises(GitError):
            orchestrate.execute(run)

        assert (git_repo / ".drydock-report.json").exists()
        assert _git(git_repo, "rev-parse", run.branch) == accepted_tip

    def test_existing_branch_with_no_results_is_still_refused(self, git_repo):
        """Even a run with nothing in `results` yet is not new, if the
        branch for its id is already there - results can be stripped by the
        resume cleanup above before this ever runs."""
        run = Run.start(git_repo, "do the thing")
        Repo(git_repo).branch(run.branch)
        _git(git_repo, "commit", "--allow-empty", "-q", "-m", "old accepted work")
        accepted_tip = _git(git_repo, "rev-parse", "HEAD")
        _git(git_repo, "checkout", "main")

        run.anchor = ""
        assert run.results == []
        (git_repo / ".drydock-report.json").write_text("{}\n")

        with pytest.raises(GitError):
            orchestrate.execute(run)

        assert (git_repo / ".drydock-report.json").exists()
        assert _git(git_repo, "rev-parse", run.branch) == accepted_tip

    def test_a_genuinely_new_run_is_unaffected(self, git_repo):
        """The guard must not catch the run it was never meant for: a fresh
        id whose branch has never existed."""
        run = Run.start(git_repo, "do the thing")
        assert not Repo(git_repo).branch_exists(run.branch)
        assert run.results == []
        assert run.expected_tip == ""
