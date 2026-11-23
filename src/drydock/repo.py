"""Git operations on the repository under work.

Every item gets its own commit, which is what makes reverting an item cheap
enough to be the default response to a failure rather than a last resort.
"""

import os
import shutil
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


# Pictures of the page as the last attempt left it, put where the engineer
# can open them. A module constant rather than only a class attribute,
# because the orchestrator needs the name without needing a repository -
# and the tests that stand in for one are not going to grow an attribute
# every time this class does.
OUR_LOOK = ".drydock-look"

# Everything this program writes into somebody's repository, in one
# place, because it was in six and two of them disagreed.
#
# `look.py` writes the pictures, `discard` keeps them on purpose so a
# second attempt can open what the first was refused for, `sweep`
# removes them before any commit, and the review diff excludes them.
# Four places knew they were ours. The two cleanliness checks did not,
# and read a directory this program had deliberately left behind as
# somebody's uncommitted work.
#
# What that cost, once: a site that was written, whose sixteen tests
# all passed, abandoned at the integration check over `?? .drydock-look/`
# and reported as though the work had failed.
OUR_FILES = (".drydock-report.json", ".drydock-out.json", ".drydock-preview.log")


def ours(path: str) -> bool:
    """Whether a path in somebody's tree is one this program put there.

    Deliberately narrow. Exact names, and one directory matched by its
    first segment - not a prefix, not a pattern, and nothing a worker
    can choose. A file somebody wrote is never ours, however it is
    spelt, because the list is a list rather than a rule.
    """
    said = (path or "").strip().strip('"')
    if not said:
        return False
    return said.split("/")[0] == OUR_LOOK or said in OUR_FILES


def _said_about(line: str) -> str:
    """The path a `git status --porcelain` line is about.

    `XY path`, and a rename is `XY old -> new`, where the new name is
    the one that exists now.
    """
    return line[3:].split(" -> ")[-1].strip().strip('"')


class GitError(RuntimeError):
    """Git could not establish the state needed to continue safely."""


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _git(self, args: str) -> tuple[int, str]:
        return run(f"git {args}", self.path, timeout=120)

    def head(self) -> str:
        """The commit this repository is on, or nothing.

        `splitlines()[0]` on its own is an IndexError the moment git says
        nothing - a repository with no commits, a worktree that has been
        taken away under a stopped run - and an IndexError is the least
        readable way to be told either of those.
        """
        # The exit code, not just the output. Without it a repository with
        # no commits returns "fatal: Needed a single revision" and every
        # caller treats that sentence as a commit hash - which is the same
        # bug as reading git's refusal as a diff, found twice today.
        said = self._asked("rev-parse --short HEAD").splitlines()
        return said[0] if said else ""

    def is_clean(self) -> bool:
        """Whether anything is here that somebody would have to explain."""
        return not self.dirt()

    def dirt(self) -> str:
        """What is uncommitted here that is not this program's own.

        Not everything git calls a change. See `ours`: the answer file a
        worker writes, the preview log, and the pictures `discard` keeps
        on purpose are all things this program put here and is going to
        take away again. Counting them as somebody's work put two of our
        own decisions in direct contradiction - one kept the pictures,
        the other refused to go on while they existed - and threw away a
        finished site over it.

        Everything else still counts, exactly as it did.
        """
        return "\n".join(
            line
            for line in self._git("status --porcelain")[1].splitlines()
            if line.strip() and not ours(_said_about(line))
        )

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
        self._checked(
            f'{self._as_whoever()}commit -q --allow-empty -m "before drydock"'
        )

    def _as_whoever(self) -> str:
        """Who to sign a commit as, when git has nobody.

        A machine where `git config user.email` was never set cannot
        commit at all, and that is the same machine as the one with a
        folder that was `git init`-ed and left - a new laptop, a
        container, CI. Refusing there means refusing to work for the
        person this was written for.

        Written for the baseline commit and then used only there, which
        meant the two commits that matter were not covered: an item's own
        commit died with "Author identity unknown", and `checkpoint`
        returned nothing at all - so the work it exists to preserve was
        thrown away unrecoverably, on exactly the machine the fallback
        was written for. Caught by CI, where no identity is set.

        Only a fallback: where an identity exists it is used, because the
        files being committed are theirs. Nothing is ever written to
        anybody's git config.
        """
        if self._git("config user.email")[0] == 0:
            return ""
        return "-c user.name=drydock -c user.email=drydock@localhost "

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
        # What is here that is not ours. See `dirt`.
        status = self.dirt()
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
        """What changed here that somebody wrote.

        `commit` asks this to decide whether there is anything to
        commit, so a tree holding nothing but our own leftovers must
        answer no - otherwise an item that wrote nothing commits the
        pictures of the page it did not change.
        """
        _, out = self._git("status --porcelain")
        return [
            _said_about(line)
            for line in out.splitlines()
            if line.strip() and not ours(_said_about(line))
        ]

    def commit(self, message: str) -> str | None:
        """Commit whatever changed. Returns the hash, or None if nothing did."""
        if not self.changed_files():
            return None
        self._checked("add -A")
        self._checked(f"{self._as_whoever()}commit -q -m {_quote(message)}")
        return self._checked("rev-parse --verify HEAD")

    # Files this application writes into somebody's repository. They are
    # written there because a worker has to put its answer somewhere the
    # worker can reach, and they are removed because leaving them would mean
    # drydock dirtying a tree it then refuses to work in.
    OURS = OUR_FILES
    # Pictures of the page as the last attempt left it, put where the
    # engineer can open them. A directory rather than a file because there
    # are two of them, and swept like the rest so it never reaches a commit.
    OUR_LOOK = OUR_LOOK

    def sweep(self) -> list[str]:
        """Remove anything drydock itself left behind. Returns what went."""
        gone = []
        for name in self.OURS:
            path = self.path / name
            if path.exists():
                path.unlink()
                gone.append(name)
        look = self.path / self.OUR_LOOK
        if look.is_dir():
            # A tree, not a flat directory. Looking at a second route puts
            # its pictures in a directory of its own, and this walked the
            # top level calling `unlink` on whatever it found - which on a
            # directory is `Operation not permitted`, raised out of the
            # sweep, which runs before the commit. So every run that
            # looked at more than one page died at the end with the work
            # finished, built and tested, and nothing recorded. Measured
            # once, on the first run of a benchmark.
            shutil.rmtree(look, ignore_errors=True)
            if not look.exists():
                gone.append(self.OUR_LOOK)
        return gone

    def checkpoint(self, why: str = "") -> str:
        """Write the uncommitted work into the object database, unreferenced.

        Call it immediately before discarding. `write-tree` and
        `commit-tree` make a commit object that no branch points at:
        nothing in the worktree moves, no ref changes, and `git show
        <hash>` reads the whole of it back afterwards.

        This exists because of one run. A site that worked, with
        sixteen passing tests, was discarded after two refusals and was
        gone - every file untracked, so nothing had ever entered the
        object database, and `git fsck` found one empty blob. Throwing
        the work away was right; a refused item costs nothing and that
        is what makes the rollback affordable. What was wrong is that
        nobody could look at it afterwards.

        `git stash create` is the obvious tool and is the wrong one: it
        keeps tracked modifications and drops untracked files, which on
        a greenfield item is all of them.

        The index is staged to do it, which is safe only because the
        discard that follows resets it. Our own leftovers are excluded
        so a checkpoint is the work and not the pictures of it.

        Never raises. A checkpoint that fails must not stop a discard.
        """
        if not self.changed_files():
            return ""
        keep = f"':(exclude){_quote(self.OUR_LOOK)}'"
        if self._git(f"add -A -- . {keep}")[0]:
            return ""
        code, tree = self._git("write-tree")
        tree = tree.strip()
        if code or not tree:
            return ""
        head = self.head()
        parent = f"-p {_quote(head)}" if head else ""
        message = _quote(why.strip()[:200] or "work discarded by drydock")
        code, made = self._git(
            f"{self._as_whoever()}commit-tree {_quote(tree)} {parent} -m {message}"
        )
        made = made.strip()
        return made if code == 0 and made else ""

    def discard(self) -> None:
        """Throw away uncommitted work. The undo button for a failed item.

        Everything except the pictures of what the attempt looked like.
        Those are the one thing the next attempt has that the last one did
        not, and cleaning them away leaves the engineer reading a sentence
        about a photograph again. They are swept before any commit, so
        keeping them here cannot put them in one.
        """
        self._git("reset --hard -q HEAD")
        self._git(f"clean -fdq -e {_quote(self.OUR_LOOK)}")

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
        excludes = " ".join(
            f"':(exclude){name}'" for name in (*self.GENERATED, self.OUR_LOOK)
        )
        return self._git(f"diff --no-color HEAD -- . {excludes}")[1]

    def pending(self) -> str:
        """Everything changed but not yet committed, including new files.

        The inspector and the reviewer both look at an item before it is
        committed, because the decision they are part of is whether it should
        be committed at all. `--no-color` and a fixed context keep the text
        stable enough to be quoted back in a verdict.

        Our own pictures are not part of it. They are written into the tree
        being worked on so the engineer can open them, and they were
        arriving in the diff the gates read as lines saying "Binary files
        /dev/null and b/.drydock-look/desktop.png differ" - noise in the one
        text an item is judged on, and more of it the more anybody looks.
        """
        self._git("add -A -N")
        return self._git(f"diff --no-color HEAD -- . ':(exclude){self.OUR_LOOK}'")[1]

    def show(self, commit: str) -> str:
        """What one commit changed, as a diff.

        Each item is its own commit, so this is exactly the change one item
        made - which is the only unit at which a reader can usefully ask
        whether they agree with it.
        """
        return self._git(f"show --no-color --stat --patch {_quote(commit)}")[1]

    def what_changed(self) -> tuple[str, str]:
        """The change worth reviewing, and a sentence saying which it is.

        Asked in this order because it is the order somebody means. A dirty
        tree is what they are working on now. A branch that is not the
        trunk is the work they would open a pull request for. Otherwise the
        last commit, which is what they just did.

        Empty when there is nothing: a clean trunk with nothing to say is
        not an error, and reporting on a diff of nothing is worse than
        saying there is nothing.
        """
        pending = self._pending_without_touching_anything()
        if pending:
            return pending, "Everything changed here and not yet committed."

        _, branch = self._git("symbolic-ref --quiet --short HEAD")
        branch = branch.strip()
        trunk = self._trunk()
        if branch and trunk and branch != trunk:
            code, base = self._git(f"merge-base {_quote(trunk)} HEAD")
            base = base.strip()
            if code == 0 and base:
                said = self._asked(f"diff --no-color {base}..HEAD")
                if said:
                    return said, f"Everything on `{branch}` since it left `{trunk}`."

        # Only when there is a commit before this one. A repository with a
        # single commit has no `HEAD~1`, and git says so on stderr - which,
        # read without its exit code, came back as a diff whose contents
        # were the words "fatal: ambiguous argument".
        if self._git("rev-parse --verify --quiet HEAD~1")[0] == 0:
            last = self._asked("diff --no-color HEAD~1..HEAD")
            if last:
                return last, "The last commit."
        return "", "there is nothing changed here to read"

    def _pending_without_touching_anything(self) -> str:
        """The uncommitted change, with the index left exactly as found.

        `pending_for_review` runs `git add -A -N` so that files nobody has
        tracked yet appear in the diff. That is right during a run - this
        program owns that tree - and wrong here, where the whole promise is
        that reading a change does not change it. Watched happen: an
        untracked file went from `??` to ` A` because somebody asked what
        was wrong with their work.

        So the files that were untracked before are written down, marked,
        read, and put back exactly as they were. Nothing else in the index
        is touched, which rules out `git reset` - somebody may have staged
        something deliberately and it is not this function's to unstage.
        """
        untracked = [
            line[3:].strip()
            for line in self._git("status --porcelain")[1].splitlines()
            if line.startswith("??")
        ]
        if untracked:
            self._git("add -N -- " + " ".join(_quote(p) for p in untracked))
        try:
            excludes = " ".join(
                f"':(exclude){name}'" for name in (*self.GENERATED, self.OUR_LOOK)
            )
            return self._asked(f"diff --no-color HEAD -- . {excludes}")
        finally:
            if untracked:
                self._git("reset -q -- " + " ".join(_quote(p) for p in untracked))

    def _asked(self, args: str) -> str:
        """The output of a git command, or nothing if it did not work.

        Every caller of this wants a diff and none of them want an error
        message that reads like one.
        """
        code, out = self._git(args)
        return out.strip() if code == 0 else ""

    def _trunk(self) -> str:
        """What this repository treats as its trunk.

        Asked of the remote first, because that is where the answer is
        written down rather than guessed: `origin/HEAD` is whatever the
        clone was told the default branch is, including `develop` and
        whatever else somebody chose. Only then the usual local names, for
        a repository with no remote at all.

        Returning "" is not a failure - a repository on its trunk has no
        branch to compare against, and the last commit is read instead.
        """
        code, said = self._git("symbolic-ref --quiet --short refs/remotes/origin/HEAD")
        named = said.strip().removeprefix("origin/")
        if code == 0 and named:
            return named
        for name in ("main", "master", "trunk", "develop"):
            for where in ("refs/heads/", "refs/remotes/origin/"):
                if self._git(f"show-ref --verify --quiet {where}{name}")[0] == 0:
                    return name
        return ""

    def diff(self, against: str = "HEAD~1") -> str:
        return self._git(f"diff {against} --unified=3")[1]


def _quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"
