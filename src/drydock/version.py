"""Which Drydock is actually running.

A server started before a commit keeps the code it was started with. The
modules are imported once and nothing re-reads them, so a fix that is in
the repository and not in the process is a fix that does not exist for
the run in front of you - and nothing anywhere said so.

That cost four separate mistakes in one afternoon: a benchmark started
against a server two commits behind, twice; a critic prompt fix that was
on disk and not in the process; a deadline that could not be passed
because the field was in a file the server had never read. Each time the
only clue was behaviour that did not match the code.

So the process records what it was when it started, the repository is
asked what it is now, and the difference is shown rather than left to be
discovered.
"""

import subprocess
from functools import cache
from pathlib import Path


def _repo() -> Path:
    """The checkout this module was imported from, if it is one."""
    return Path(__file__).resolve().parent.parent.parent


def _commit(where: Path) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(where), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


@cache
def loaded() -> str:
    """The commit this process is running, read once when it starts.

    Cached on purpose. Reading it again later would report the
    repository's commit rather than the process's, which is exactly the
    confusion this exists to end.
    """
    return _commit(_repo())


def on_disk() -> str:
    """The commit the repository is on now. Read fresh every time."""
    return _commit(_repo())


def status() -> dict:
    """What is running, what is checked out, and whether they agree.

    `stale` is only true when both are known and they differ. An
    installation rather than a checkout has no commit for either, and a
    program that cannot tell says so rather than guessing that it is
    current.
    """
    running, current = loaded(), on_disk()
    return {
        "loaded": running,
        "on_disk": current,
        "short": running[:7],
        "stale": bool(running and current and running != current),
        "known": bool(running),
    }
