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

    def diff(self, against: str = "HEAD~1") -> str:
        return self._git(f"diff {against} --unified=3")[1]


def _quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"
