"""Git operations on the repository under work.

Every item gets its own commit, which is what makes reverting an item cheap
enough to be the default response to a failure rather than a last resort.
"""

from pathlib import Path

from .shell import run


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _git(self, args: str) -> tuple[int, str]:
        return run(f"git {args}", self.path, timeout=120)

    def head(self) -> str:
        return self._git("rev-parse --short HEAD")[1].strip().splitlines()[0]

    def is_clean(self) -> bool:
        return not self._git("status --porcelain")[1].strip()

    def branch(self, name: str) -> None:
        self._git(f"checkout -B {name}")

    def changed_files(self) -> list[str]:
        _, out = self._git("status --porcelain")
        return [line[3:].strip() for line in out.splitlines() if line.strip()]

    def commit(self, message: str) -> str | None:
        """Commit whatever changed. Returns the hash, or None if nothing did."""
        if not self.changed_files():
            return None
        self._git("add -A")
        self._git(f"commit -q -m {_quote(message)}")
        return self.head()

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
