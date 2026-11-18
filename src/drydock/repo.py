"""Git operations on the repository under work.

Every item gets its own commit, which is what makes reverting an item cheap
enough to be the default response to a failure rather than a last resort.
"""

import os
from pathlib import Path

from .shell import run

# Directories a project installs rather than writes, which git therefore
# does not carry into a second working copy. Without them the first thing a
# worker does in a worktree is install the whole dependency tree again -
# minutes of it, per item, per run - and four items working at once means
# four installs of the same thing. They are lent rather than copied: a link
# costs nothing and the originals are read, not written.
LENT = ("node_modules", ".venv", "venv", "vendor/bundle")


def _lend_dependencies(repo: Path, where: Path) -> None:
    for name in LENT:
        source = repo / name
        if not source.is_dir():
            continue
        target = where / name
        if target.exists() or target.is_symlink():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=True)
        except OSError:
            # Not fatal. The worker installs them itself, slowly, which is
            # what happened before this existed.
            pass


class GitError(RuntimeError):
    """Git could not establish the state needed to continue safely."""


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _git(self, args: str) -> tuple[int, str]:
        return run(f"git {args}", self.path, timeout=120)

    def head(self) -> str:
        return self._git("rev-parse --short HEAD")[1].strip().splitlines()[0]

    def is_clean(self) -> bool:
        return not self._git("status --porcelain")[1].strip()

    def has_history(self) -> bool:
        """Whether anything has ever been committed here.

        `git init` and nothing else leaves a real repository with no HEAD at
        all, which is not the same as an empty one: every check here reads
        HEAD, and the first thing a run does with a repository is ask where
        its branch is.
        """
        return self._git("rev-parse --verify --quiet HEAD")[0] == 0

    def start_history(self) -> None:
        """Give a repository with no commits a first one, or do nothing.

        An item that fails is undone by throwing away its commit, so a run
        needs a commit to go back to. With no HEAD there is nothing to roll
        back to and nothing to compare a branch against.

        This commits whatever is already in the folder, which is the one
        case where writing a commit without asking is the careful thing to
        do: nothing is overwritten or moved, and the alternative is refusing
        to work and telling somebody to go and run two git commands. A
        repository that does have history is left exactly alone - there the
        refusal stands, because an uncommitted change in a tree with history
        is work somebody did and may not want folded into a baseline.
        """
        if self.has_history():
            return
        self._checked("add -A")
        self._checked('commit -q --allow-empty -m "before drydock"')

    def branch(self, name: str) -> None:
        # -b, not -B: a branch that already exists is refused rather than
        # moved. The caller that is allowed to pick up an existing branch
        # is resume, not this one - see branch_exists.
        self._checked(f"checkout -b {_quote(name)}")
        self.require_checkout(name)

    def branch_exists(self, name: str) -> bool:
        """A read-only check, so it is safe to call before deciding
        whether this run is new or picking up an old branch by surprise."""
        code, out = self._git(f"show-ref --verify --quiet refs/heads/{_quote(name)}")
        if code == 0:
            return True
        if code == 1:
            return False
        raise GitError(f"git show-ref failed (exit {code}): {out.strip()[-600:]}")

    def _checked(self, args: str) -> str:
        code, out = self._git(args)
        if code:
            raise GitError(f"git {args} failed (exit {code}): {out.strip()[-600:]}")
        return out.strip()

    def require_checkout(self, branch: str, tip: str | None = None) -> str:
        """Check ownership and cleanliness before running checks or restoring."""
        _, current = self._git("symbolic-ref --quiet --short HEAD")
        current = current.strip() or "(detached)"
        if not self.has_history():
            # Said plainly, because the raw version of this - "git rev-parse
            # --verify HEAD failed (exit 128)" - ended a run in a way nobody
            # could act on.
            raise GitError(
                f"{self.path} is a git repository with no commits yet, so "
                f"there is no state to verify {branch} against or to undo a "
                "failed item back to"
            )
        head = self._checked("rev-parse --verify HEAD")
        status = self._checked("status --porcelain")
        if current != branch or (tip and head != tip) or status:
            raise GitError(
                f"expected clean {branch} at {tip or 'its tip'}, "
                f"observed {current} at {head}"
                + (f" with changes: {status}" if status else "")
            )
        return head

    def restore_tip(self, branch: str, candidate: str, previous: str) -> None:
        self.require_checkout(branch, candidate)
        # --keep refuses to overwrite local modifications made after the check.
        self._checked(f"reset --keep {_quote(previous)}")
        self.require_checkout(branch, previous)

    def require_parent(self, candidate: str, previous: str) -> None:
        observed = self._checked(f"show -s --format=%P {_quote(candidate)}")
        if observed != previous:
            raise GitError(
                f"expected parent {previous}, observed {observed or '(none)'}"
            )

    def changed_files(self) -> list[str]:
        _, out = self._git("status --porcelain")
        return [line[3:].strip() for line in out.splitlines() if line.strip()]

    def commit(self, message: str) -> str | None:
        """Commit whatever changed. Returns the hash, or None if nothing did."""
        if not self.changed_files():
            return None
        self._checked("add -A")
        self._checked(f"commit -q -m {_quote(message)}")
        return self._checked("rev-parse --verify HEAD")

    # Files this application writes into somebody's repository. They are
    # written there because a worker has to put its answer somewhere the
    # worker can reach, and they are removed because leaving them would mean
    # drydock dirtying a tree it then refuses to work in.
    OURS = (".drydock-report.json", ".drydock-out.json", ".drydock-preview.log")

    def sweep(self) -> list[str]:
        """Remove anything drydock itself left behind. Returns what went."""
        gone = []
        for name in self.OURS:
            path = self.path / name
            if path.exists():
                path.unlink()
                gone.append(name)
        return gone

    def discard(self) -> None:
        """Throw away uncommitted work. The undo button for a failed item."""
        self._git("reset --hard -q HEAD")
        self._git("clean -fdq")

    # Files that are generated rather than written. They belong in the commit
    # and they do not belong in a review: a lockfile of two thousand lines
    # pushes the three files somebody actually wrote out of the diff entirely.
    GENERATED = (
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "Cargo.lock",
        "poetry.lock",
        "uv.lock",
        "Gemfile.lock",
        "composer.lock",
        "go.sum",
        "*.min.js",
        "*.min.css",
    )

    def worktree(self, name: str, at: str) -> Path:
        """A second working copy of this repository, sharing its history.

        Two workers cannot edit one checkout: they would see each other's
        half-finished files and the diff of either would contain the other's
        work. A worktree gives each one its own files and the same git, so
        the commits land in the same place and nothing is copied.
        """
        # Under this program's own directory, not beside the repository.
        # The parent of a repository is usually the folder holding every
        # other one somebody owns, and leaving working copies in it - which
        # happens whenever a run is killed - puts drydock's debris among
        # their projects.
        home = Path(os.environ.get("DRYDOCK_HOME") or Path.home() / ".drydock")
        where = home / "worktrees" / f"{self.path.name}-{name}"
        where.parent.mkdir(parents=True, exist_ok=True)
        if where.exists():
            self._git(f"worktree remove --force {_quote(str(where))}")
        code, out = self._git(
            f"worktree add --detach {_quote(str(where))} {_quote(at)}"
        )
        if code:
            raise RuntimeError(f"could not make a worktree: {out[-400:]}")
        _lend_dependencies(self.path, where)
        return where

    def drop_worktree(self, where: Path) -> None:
        self._git(f"worktree remove --force {_quote(str(where))}")

    def take(self, commit: str) -> tuple[bool, str]:
        """Bring one commit onto this branch. False when it will not apply.

        cherry-pick rather than merge: each item is one commit and stays one
        commit, which is what makes the history readable and a single item
        revertable. A conflict means two items touched the same lines after
        the planner said they would not, and the honest answer is to put that
        item back in the queue rather than to resolve it blind.
        """
        code, out = self._git(f"cherry-pick --allow-empty {_quote(commit)}")
        if code:
            self._git("cherry-pick --abort")
            return False, out[-500:]
        return True, self._checked("rev-parse --verify HEAD")

    def pending_for_review(self) -> str:
        """The uncommitted change, without the parts nobody wrote by hand."""
        self._git("add -A -N")
        excludes = " ".join(f"':(exclude){name}'" for name in self.GENERATED)
        return self._git(f"diff --no-color HEAD -- . {excludes}")[1]

    def pending(self) -> str:
        """Everything changed but not yet committed, including new files.

        The inspector and the reviewer both look at an item before it is
        committed, because the decision they are part of is whether it should
        be committed at all. `--no-color` and a fixed context keep the text
        stable enough to be quoted back in a verdict.
        """
        self._git("add -A -N")
        return self._git("diff --no-color HEAD")[1]

    def show(self, commit: str) -> str:
        """What one commit changed, as a diff.

        Each item is its own commit, so this is exactly the change one item
        made - which is the only unit at which a reader can usefully ask
        whether they agree with it.
        """
        return self._git(f"show --no-color --stat --patch {_quote(commit)}")[1]

    def diff(self, against: str = "HEAD~1") -> str:
        return self._git(f"diff {against} --unified=3")[1]


def _quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"
