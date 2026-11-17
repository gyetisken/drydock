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


def take(
    url: str, into: Path, widths: tuple[str, ...] = ("desktop", "phone")
) -> list[Shot]:
    """Render the page at each width. Empty when there is no browser to do it.

    Raises nothing on a missing browser: a check that cannot run has to say
    so to whoever asked, not take the run down.
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
            subprocess.run(  # the browser is one already installed here
                [
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
                    url,
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
        if out.exists() and out.stat().st_size > 1000:
            shots.append(Shot(width=name, path=out))
    return shots
