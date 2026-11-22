"""Whose fault an exception was, and how to say so.

`except Exception` is right wherever one failure must not take a run
down, and wrong the moment it makes every failure read the same. A model
that would not answer, a machine with no browser, and a `TypeError` in
this program's own code all arrived as one line of feed text with no
type, no file and no line - and the last of those is the only one a
person can fix. Three times in this project a bug of ours was read as
the work being unverifiable, because that is what the message said.

So the kind is asked. The shapes below are what a program gets wrong
about itself: a name that is not there, a value of the wrong type, an
index past the end. When one of them arrives it is named as ours,
pointed at the line it came from, and its traceback is printed where a
person will see it. Anything else is the world - a process, a socket, a
model, a file - and is reported as it always was, because it is not a
bug.

Nothing here raises. A failure in the code that explains failures would
be the worst one to have.
"""

import contextlib
import sys
import traceback
from pathlib import Path

#: Exceptions that mean this program is wrong, rather than something it
#: depends on being unavailable. `ValueError` is deliberately absent: a
#: malformed JSON payload arrives as one, and that is a worker's doing.
#: `OSError` likewise - a missing file is the world, not a mistake here.
OURS = (
    AssertionError,
    AttributeError,
    IndexError,
    KeyError,
    NameError,  # UnboundLocalError is a subclass of this
    NotImplementedError,
    TypeError,
    ZeroDivisionError,
)

_HERE = str(Path(__file__).resolve().parent)


def is_ours(exc: BaseException) -> bool:
    """Whether this is a mistake in drydock rather than a refusal by it."""
    return isinstance(exc, OURS)


def where(exc: BaseException) -> str:
    """The deepest frame inside this package, as `file.py:line`.

    The deepest rather than the first: the top of a traceback is the
    orchestrator calling something, which is never the interesting line.
    """
    try:
        ours = [
            frame
            for frame in traceback.extract_tb(exc.__traceback__)
            if str(Path(frame.filename).resolve()).startswith(_HERE)
        ]
        if not ours:
            return ""
        last = ours[-1]
        return f"{Path(last.filename).name}:{last.lineno}"
    except Exception:  # noqa: BLE001 - never the cause of a failure
        return ""


def plainly(exc: BaseException) -> str:
    """One line for whoever is watching, which says whose fault it was."""
    name = type(exc).__name__
    said = (str(exc) or "").strip() or "no message"
    if not is_ours(exc):
        return f"{name}: {said}"
    spot = where(exc)
    at = f" at {spot}" if spot else ""
    return f"a bug in drydock{at}, not in the work - {name}: {said}"


def trace(exc: BaseException) -> str:
    """The whole traceback, or nothing if it cannot be formatted."""
    try:
        return "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).rstrip()
    except Exception:  # noqa: BLE001 - never the cause of a failure
        return ""


def report(station: str, exc: BaseException, on_event=None, *, note: str = "") -> str:
    """Say it under the station that hit it, and keep the traceback.

    The one line goes to whoever is watching the run; the traceback goes
    to the console, which is the only thing that fixes a bug of ours. It
    is printed for our own only, because a browser that is not installed
    does not need thirty lines to explain itself.

    Returns the line, so a caller can put the same words in the record
    rather than inventing a second description of the same failure.
    """
    said = plainly(exc)
    if note:
        said = f"{note}: {said}"
    if is_ours(exc):
        print(
            f"\ndrydock bug, hit by the {station}: {said}\n{trace(exc)}\n",
            file=sys.stderr,
            flush=True,
        )
    if on_event:
        # A feed that will not take this is not the failure being reported.
        with contextlib.suppress(Exception):
            on_event(station, said)
    return said
