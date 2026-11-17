"""Taking a picture of the page.

Everything else in this program judges work by reading it. A test suite reads
behaviour, the inspector reads a diff, the reviewer reads a change against
the item it was given. None of them can see, and the failures that make a
page bad are all visual: one flat column where there should be structure, a
hierarchy that does not exist, a hero that pushes everything below the fold,
text at four-point contrast against its background.

So this renders the page and hands back an image, and a station that can look
at images looks at it. No new dependency: it drives whatever browser is
already on the machine in headless mode, and says plainly when there is not
one rather than pretending the check happened.
"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Where the usual browsers live, in the order worth trying. Chrome and Edge
# both take --screenshot directly, which is the whole reason this needs no
# library.
CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
)

WIDTHS = {"phone": (420, 1800), "desktop": (1440, 2200)}


@dataclass
class Shot:
    width: str
    path: Path


def find_browser() -> str:
    for candidate in CANDIDATES:
        if "/" in candidate and Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return ""


# How long one width is given before the browser is taken away from it. A
# page that holds a connection open - a stream, a socket, a dashboard that
# polls - never finishes loading, so the browser never exits on its own and
# the budget above does not apply to it. Short, because the picture is
# usually already written by the time this matters.
PATIENCE = 20


def take(
    url: str, into: Path, widths: tuple[str, ...] = ("desktop", "phone")
) -> list[Shot]:
    """Render the page at each width. Empty when there is no browser to do it.

    Raises nothing, ever. A check that could not run has to say so to
    whoever asked for it, not take the run down - and the page most worth
    looking at is often the one least willing to finish loading.
    """
    browser = find_browser()
    if not browser:
        return []

    into.mkdir(parents=True, exist_ok=True)
    shots = []
    for name in widths:
        width, height = WIDTHS[name]
        out = into / f"{name}.png"
        with tempfile.TemporaryDirectory(prefix="drydock-shot-") as profile:
            command = [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-color-profile=srgb",
                f"--user-data-dir={profile}",
                f"--window-size={width},{height}",
                f"--screenshot={out}",
                # Long enough for fonts and any entrance animation; short
                # enough that a hung page does not hold up a run.
                "--virtual-time-budget=4000",
                # Take the picture even if the page never finishes loading.
                # Anything holding a connection open - a stream, a socket, a
                # dashboard that polls - never finishes, and without this the
                # browser waits for it and the page is never looked at. Which
                # is the wrong way round: a live page is the one most worth
                # looking at.
                "--timeout=6000",
                url,
            ]
            try:
                subprocess.run(  # the browser is one already installed here
                    command, capture_output=True, timeout=PATIENCE, check=False
                )
            except subprocess.TimeoutExpired:
                # It would not leave. The picture is very often already on
                # disk by this point - the page rendered and then went on
                # waiting for a connection that does not end - so the file is
                # checked below either way, and this is not an error unless
                # it turns out there is nothing there.
                pass
            except OSError:
                return shots
        if out.exists() and out.stat().st_size > 1000:
            shots.append(Shot(width=name, path=out))
    return shots
