"""Running commands inside the repository under work.

Agents do not get a shell. They get this, which takes a command from a short
allow-list in the repository's own configuration and nothing else. The point is
not that a model would deliberately do something reckless; it is that a loop
which can run arbitrary commands has no bound on what a bad turn costs, and an
agent that can only run the build and the tests has a very small one.
"""

import shlex
import subprocess
import time
from pathlib import Path

from .models import Check


class CommandRefused(Exception):
    pass


def run(command: str, cwd: Path, timeout: int = 900) -> tuple[int, str]:
    """Run one command and return its exit code and combined output.

    The output is the command's own and nothing else. An earlier version
    appended the elapsed time, which meant `git status --porcelain` never
    came back empty and the tree was never clean.
    """
    try:
        # shlex.split, never shell=True: the command comes from the
        # repository's own configuration, and a shell would turn a stray
        # semicolon in it into a second command.
        done = subprocess.run(
            shlex.split(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,  # a failing build is data, not an exception
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def check(name: str, command: str, cwd: Path, timeout: int = 900) -> Check:
    started = time.monotonic()
    code, output = run(command, cwd, timeout)
    return Check(
        name=name,
        command=command,
        passed=code == 0,
        seconds=round(time.monotonic() - started, 1),
        detail=_tail(output),
    )


def _tail(output: str, lines: int = 40) -> str:
    """Keep the end of the output. Build failures report at the bottom."""
    kept = output.strip().splitlines()[-lines:]
    return "\n".join(kept)
