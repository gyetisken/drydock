"""Looking at what you just built, before anybody else does.

The engineer could not see its own work. It had Read, Edit, Write, Glob,
Grep and the project's build command, and that is all - so it wrote a page,
reported, and the first eyes on it belonged to the critic, after the item
was finished and with the only remedy being to throw the item away and do
it again. Twelve items in one run were written by somebody who never saw
any of them.

This is the one command that closes that: it starts the project the way the
project says it starts, measures the page, photographs it at two widths and
hands back the paths. The engineer opens the pictures with Read, fixes what
it finds, and looks again - inside the one attempt, before anything is
committed and before anybody independent is asked.

Three things it is careful about.

It is not a verdict. Everything here is measurement and photographs; the
build, the suite, the diff and the critic all still happen afterwards and
none of them is told that this ran. A worker that looks is not a worker
that has been checked.

It never claims a look that did not happen. A project that will not start,
a machine with no browser, a page that is not a page - each ends with
NOT LOOKED and a reason, because the failure mode that matters here is a
report saying the page was checked when nothing was ever rendered.

It is bounded per item, not per directory. Items run one after another in
the same tree, so a tally kept by directory would let item 1 spend item 7's
looks. The key comes from the run and the item, and it is kept outside the
repository where the worker cannot edit it.
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import preview, probe
from .fits import why_it_does_not_fit
from .repo import OUR_LOOK
from .route import is_route, slug
from .shot import take

# What may be asked for lives in `route`, which the confinement hook reads
# too. It was a pattern here whose comment said a `..` was refused and
# whose character class allowed it, and the hook had a different rule
# again - which is how `drydock-look /rooms` came to be refused by the
# confiner for being a filesystem path and by this command for not
# beginning with a slash, depending on which way it was spelt. One rule,
# read by both ends of the door.

# How many routes one invocation may name. Not the budget - that is
# counted in pages below - but a guard on a command line that has got
# away from whoever typed it.
AT_ONCE = 6

# The two widths everything else here already uses: a phone and a laptop.
PHONE, DESKTOP = 390, 1440

# Said when there is no tally to keep, which means nobody set a budget.
# Looking is refused rather than allowed in that case: an unbounded loop of
# browser launches inside a worker's clock is the thing the budget exists to
# stop.
NO_BUDGET = "no look budget was set for this item"

# The three things the first line can say, kept as constants because what
# the worker and the tests both depend on is this exact word.
#
# MEASURED_ONLY is the one that matters. The browser read the page and the
# camera failed, which is not a look at it: there is nothing to open, and a
# heading saying LOOKED would be read as having seen it. Separating them is
# the whole of "never record a look that did not happen".
LOOKED = "LOOKED"
MEASURED_ONLY = "MEASURED ONLY, NOT SEEN"

NOT_A_CHECK = (
    "This is not a check that counts. What you write is still built, its "
    "suite still run, its diff still read, and the page still measured and "
    "looked at by somebody who is not you. None of them is told that you "
    "looked - looking is only how you stop handing on work nobody has seen.\n\n"
    # Said here as well as in the system prompt because this is the moment
    # it happens: the engineer reads the pictures, sees what it wants to
    # know, and then goes and confirms it a second time from the source.
    "What you can see above, and in the pictures, you do not need to go and "
    "confirm again in the source or by asking the running page. Change what "
    "needs changing, or finish and report."
)


@dataclass
class Tally:
    """How many looks this item has had, kept where the worker cannot reach.

    One file per run and item under the drydock home. The worker's file
    tools are confined to the repository by the PreToolUse hook, so this is
    outside what it can edit - which is the point of putting it here rather
    than in the tree.
    """

    key: str
    limit: int

    @property
    def path(self) -> Path:
        home = Path(os.environ.get("DRYDOCK_HOME") or Path.home() / ".drydock")
        where = home / "looks"
        where.mkdir(parents=True, exist_ok=True)
        # The key is a run id and an item number, both of ours, but it
        # arrives through the environment so it is reduced to something
        # that cannot name a path.
        safe = re.sub(r"[^A-Za-z0-9_.-]", "-", self.key)[:120]
        return where / f"{safe}.json"

    def so_far(self) -> int:
        try:
            return int(json.loads(self.path.read_text())["looks"])
        except (OSError, ValueError, KeyError, TypeError):
            return 0

    def one_more(self) -> int:
        """Count this look. Returns which one it is, counting from one."""
        now = self.so_far() + 1
        try:
            self.path.write_text(json.dumps({"key": self.key, "looks": now}))
        except OSError:
            # A tally that cannot be written is a budget that cannot be
            # enforced, and this must not become a way to get unlimited
            # looks by making the directory unwritable.
            return self.limit + 1
        return now


def _asked_for() -> Tally | None:
    """The budget this worker was given, or nothing."""
    key = os.environ.get("DRYDOCK_LOOK_KEY", "").strip()
    try:
        limit = int(os.environ.get("DRYDOCK_LOOK_LIMIT", "0"))
    except ValueError:
        limit = 0
    if not key or limit < 1:
        return None
    return Tally(key=key, limit=limit)


def _project() -> Path | None:
    """The one directory this may start, which is not the caller's cwd."""
    root = os.environ.get("DRYDOCK_ROOT", "").strip()
    if not root:
        return None
    try:
        where = Path(root).resolve()
    except (OSError, RuntimeError):
        return None
    return where if where.is_dir() else None


def _not_looked(why: str) -> int:
    """Say that nothing was established, in words that cannot be misread."""
    print("NOT LOOKED")
    print(f"  {why}")
    print(
        "\n  Nothing about the rendered page has been established by this. "
        "Do not report that you checked it, and do not describe what it "
        "looks like - you have not seen it."
    )
    return 0


def _measured(url: str, width: int) -> tuple[list[str], probe.Looked | None]:
    """What the browser says about one width, as plain sentences."""
    seen = probe.look(url, width)
    if not seen.ran:
        return [f"the browser could not read the page at {width}px: {seen.error}"], None
    said = [f"{seen.words} words and {seen.visible} elements rendered at {width}px"]
    said += seen.findings()
    return said, seen


def _photograph(url: str, into: Path) -> tuple[list[str], str]:
    """Two pictures, or an honest account of why there are none.

    Any picture already in there is removed first. A screenshot that fails
    silently leaves the previous attempt's image on disk, and handing that
    back as what the page looks like now is exactly the lie this module is
    written to avoid.
    """
    try:
        into.mkdir(parents=True, exist_ok=True)
        for stale in into.glob("*.png"):
            stale.unlink()
    except OSError as exc:
        return [], f"could not write pictures into {OUR_LOOK}/: {exc}"

    shots = take(url, into)
    if not shots:
        return [], "no browser on this machine, so there are no pictures"
    fresh = [s for s in shots if s.path.exists() and s.path.stat().st_size > 1000]
    if not fresh:
        return [], "the browser was asked for pictures and wrote none"
    # Named from the look directory down, not by filename alone: a second
    # route's pictures live in a directory of their own, and handing back
    # `.drydock-look/desktop.png` for a picture that is at
    # `.drydock-look/rooms/desktop.png` is an unopenable path in a report
    # that says to open it.
    where = OUR_LOOK if into.name == OUR_LOOK else f"{OUR_LOOK}/{into.name}"
    named = [f"{where}/{s.path.name} ({s.width})" for s in fresh]
    # And what is not in them, when a page is taller than one picture
    # worth reading. Said with the pictures rather than left out, because
    # "I looked at the page" and "I looked at the top of the page" are
    # different reports and only one of them is true here.
    short = [s.said() for s in fresh if not s.whole]
    return named, ("; ".join(short) if short else "")


def _one_page(path: str, live, where: Path, nth: int, limit: int) -> list[str]:
    """Measure, press and photograph one route, as lines to print."""
    url = live.url.rstrip("/") + path
    served = preview.what_it_serves(live.url, path)
    if not served.is_a_page:
        return [
            f"NOT LOOKED  {path}",
            f"  {url} answered {served.said}, which is not a page.",
        ]

    # Arithmetic first, because a page wider than the screen is a number
    # rather than an opinion and it is the defect that has cost this crew
    # the most.
    overflow = why_it_does_not_fit(url)
    phone, _ = _measured(url, PHONE)
    desktop, seen = _measured(url, DESKTOP)

    # What the controls do. Establishes that a button goes somewhere, never
    # that it went to the right place - that needs somebody to have said
    # what the right place was.
    pressed = probe.press(url, DESKTOP, timeout=60)

    into = where / OUR_LOOK
    if slug(path):
        into = into / slug(path)
    pictures, why_not = _photograph(url, into)

    # The first line says what kind of look this was, and it cannot be
    # written until the pictures have been attempted. Measurement
    # succeeding while the camera failed is not a look at the page, and a
    # heading that said LOOKED either way would be the exact
    # misunderstanding this is built to prevent.
    said = [
        f"{LOOKED if pictures else MEASURED_ONLY} {nth} of {limit}",
        f"  {url}  (started with `{live.command}`)",
        "",
        "MEASURED",
    ]
    for line in ([overflow] if overflow else []) + desktop + phone:
        said += [f"  {part.strip()}" for part in line.splitlines() if part.strip()]

    if pressed:
        said += ["", "PRESSED"]
        for control in pressed:
            label = f'"{control.said[:36]}"'
            said.append(f"  {label:<40} {control.did or control.why}")

    if pictures:
        said += ["", "PICTURES"]
        said += [f"  {shot}" for shot in pictures]
        said.append(
            "  Open every one of them with Read before you change anything. "
            "The measurements above are facts about the page; the pictures "
            "are the only way you see it."
        )
        # Each picture is the whole page unless it says otherwise. When one
        # stops short, say where it stopped: a report on the top of a page
        # that reads as a report on the page is the thing all of this
        # exists to prevent.
        if why_not:
            said.append(f"  NOT ALL OF IT: {why_not}")
    else:
        said += [
            "",
            "NO PICTURES",
            f"  {why_not}",
            (
                "  The measurements above still hold. Anything about how "
                "it looks does not - you have not seen this page, so do "
                "not describe it and do not report that you looked at it."
            ),
        ]

    if seen is not None and seen.blank:
        said += [
            "",
            (
                "The page is effectively empty. Whatever is wrong is wrong "
                "before anything about how it looks matters."
            ),
        ]
    return said


def main(argv: list[str] | None = None) -> int:
    """Start it, measure it, photograph it, say what was found.

    Returns 0 whatever happens. A non-zero exit reads to a worker as a
    command it should fix, and a project that cannot be started is not
    something the worker can fix from inside the item.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    paths = args or ["/"]
    if len(paths) > AT_ONCE:
        return _not_looked(
            f"{len(paths)} pages at once, and {AT_ONCE} is the most this "
            "takes. Look at the ones that carry the item and say in your "
            "report which you did not."
        )
    for path in paths:
        if not is_route(path):
            return _not_looked(
                f"{path!r} is not a path on this project. This looks at the "
                "project it is run in and nothing else - give it a path "
                "beginning with / and no scheme, host, port or `..`."
            )
    # One page per route, so naming the same one twice does not spend two
    # looks on one answer.
    seen_already: list[str] = []
    for path in paths:
        if path.rstrip("/") not in [p.rstrip("/") for p in seen_already]:
            seen_already.append(path)
    paths = seen_already

    budget = _asked_for()
    if budget is None:
        return _not_looked(NO_BUDGET)
    where = _project()
    if where is None:
        return _not_looked("there is no project here to start")

    try:
        live = preview.running(where) or preview.start(where)
    except (LookupError, RuntimeError, TimeoutError) as exc:
        return _not_looked(f"the project did not start: {exc}")

    # A page costs a look, not an invocation. Asking for four pages with
    # two left buys two pages and an honest sentence about the other two,
    # which is the whole point of counting them.
    said: list[str] = []
    looked_at: list[str] = []
    not_looked_at: list[str] = []
    for path in paths:
        nth = budget.one_more()
        if nth > budget.limit:
            not_looked_at.append(path)
            continue
        if said:
            said += ["", "-" * 60, ""]
        said += _one_page(path, live, where, nth, budget.limit)
        looked_at.append(path)

    # Nothing at all was looked at, so this is not a look and must not
    # read as one. The heading is the contract: a worker that sees
    # anything else at the top of this output has been told something was
    # established.
    if not looked_at:
        return _not_looked(
            f"this item has had its {budget.limit} looks. Finish it with "
            "what you know, or say in your report what you could not check."
        )

    # Which pages this establishes anything about, and which it does not.
    # A report that names three pages after looking at one is the failure
    # this whole module exists to prevent, so the list is printed rather
    # than left to be inferred from the blocks above.
    said += ["", "ROUTES"]
    said.append(f"  looked at: {', '.join(looked_at) if looked_at else 'none'}")
    if not_looked_at:
        said.append(
            f"  not looked at: {', '.join(not_looked_at)} - this item has "
            f"had its {budget.limit} looks. Say so in your report rather "
            "than describing them."
        )
    said += ["", NOT_A_CHECK]
    print("\n".join(said))
    return 0


if __name__ == "__main__":
    # The clock is the worker's, so a slow look is a cost it can see.
    started = time.monotonic()
    code = main()
    print(f"\n({time.monotonic() - started:.0f}s)")
    sys.exit(code)
