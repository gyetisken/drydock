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

import os
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

WIDTHS = {"phone": (390, 1800), "desktop": (1440, 2200)}

# Taking the picture through the devtools protocol rather than with
# --screenshot, because --window-size is not a phone.
#
# A page that says `width=device-width` gets the window width on a desktop
# browser and 980px when the browser does not think it is a device - and
# headless Chrome does not. So --window-size=390 produced a picture of a
# 980px-wide page with 390px of it showing, and every narrow render looked
# like text cut off at the right edge. The critic refused eight items on
# that picture in one afternoon. The page was fine every time.
SHOOT = r"""
const [, , target, widthArg, heightArg, out] = process.argv;
const width = Number(widthArg);
const height = Number(heightArg);
// Above this a picture stops being a picture of a page. Generous: the
// LUMI site was 4,800 and the AURA one 6,200.
const TALLEST = 12000;
const { spawn } = await import('node:child_process');
const { mkdtempSync, writeFileSync } = await import('node:fs');

const chrome = spawn(process.env.DRYDOCK_BROWSER, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--force-color-profile=srgb', '--remote-debugging-port=0',
  `--window-size=${width},${height}`,
  '--user-data-dir=' + mkdtempSync('/tmp/drydock-shoot-'), 'about:blank',
]);

const stop = (said) => { console.log(said); chrome.kill(); process.exit(0); };
setTimeout(() => stop('the browser did not answer'), 40000);

const wsUrl = await new Promise((ok, no) => {
  chrome.stderr.on('data', (b) => {
    const m = /ws:\/\/[^\s]+/.exec(b.toString());
    if (m) ok(m[0]);
  });
  chrome.on('exit', () => no(new Error('the browser stopped')));
});

const ws = new WebSocket(wsUrl);
let id = 0;
const waiting = new Map();
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
};
await new Promise((ok) => { ws.onopen = ok; });
const send = (method, params = {}, sessionId) => new Promise((ok) => {
  const n = ++id;
  waiting.set(n, ok);
  ws.send(JSON.stringify({ id: n, method, params, sessionId }));
});

const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
await send('Emulation.setDeviceMetricsOverride', {
  width, height, deviceScaleFactor: 1, mobile: width < 700,
}, sessionId);
await send('Page.enable', {}, sessionId);
await send('Page.navigate', { url: target }, sessionId);
await new Promise((r) => setTimeout(r, 4000));

// The whole page, not the window it opened in. This took one shot of a
// fixed window, so a hero set to 100svh filled both pictures and the
// critic saw the arrival and nothing else - it said so itself, on a page
// with four sections under the fold: "Neither shot shows any of the four
// sections". It had been judging the top of every page it was given.
//
// Captured past the viewport rather than by making the viewport taller.
// Resizing is the obvious way and it is wrong: viewport units resolve
// against the window, so a 100svh hero grows to fill whatever height is
// asked for and pushes the rest of the page down behind it. Tried, and
// the phone picture came back five thousand pixels tall with the hero
// repeated down it and the four sections still missing. The window stays
// the size a phone is; only the picture is bigger.
//
// The cap is there because a page can be a hundred thousand pixels tall
// and a picture that large helps nobody.
const measured = await send('Runtime.evaluate', {
  expression: `Math.max(
    document.documentElement.scrollHeight, document.body.scrollHeight,
    document.documentElement.offsetHeight, ${height})`,
  returnByValue: true,
}, sessionId);
const full = Math.min(
  Math.max(Number((measured.result || {}).result?.value) || height, height),
  TALLEST,
);

const shot = await send('Page.captureScreenshot', {
  format: 'png',
  captureBeyondViewport: true,
  clip: { x: 0, y: 0, width, height: full, scale: 1 },
}, sessionId);
if (!shot.result || !shot.result.data) stop('the page would not be photographed');
writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
stop('ok');
"""


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


def _through_devtools(url: str, out: Path, width: int, height: int) -> bool:
    """Photograph the page as a device of this width would see it."""
    node = shutil.which("node")
    browser = find_browser()
    if not node or not browser:
        return False
    with tempfile.TemporaryDirectory(prefix="drydock-shoot-") as scratch:
        script = Path(scratch) / "shoot.mjs"
        script.write_text(SHOOT)
        try:
            subprocess.run(
                [node, str(script), url, str(width), str(height), str(out)],
                capture_output=True,
                text=True,
                timeout=PATIENCE + 40,
                check=False,
                env={
                    "PATH": "/usr/bin:/bin:/usr/local/bin",
                    # The environment is stripped on purpose: a browser
                    # pointed at somebody's page has no business reading
                    # this process's variables. `HOME` is the exception,
                    # and leaving it out was not isolation but an
                    # oversight - a Chrome that cannot find a home cannot
                    # find a keychain, and macOS stops the machine with a
                    # modal asking what to do about it, every time a page
                    # is photographed. It still gets its own
                    # `--user-data-dir`, so this does not hand it the
                    # person's profile.
                    "HOME": os.environ.get("HOME", ""),
                    "DRYDOCK_BROWSER": browser,
                },
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    return out.exists() and out.stat().st_size > 1000


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
        if _through_devtools(url, out, width, height):
            shots.append(Shot(width=name, path=out))
            continue
        # No Node on this machine. The flag alone cannot emulate a device,
        # so a narrow picture taken this way is a crop of a wide page
        # rather than a phone - usable for colour and hierarchy, not for
        # anything about what fits.
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
                "--virtual-time-budget=4000",
                "--timeout=6000",
                url,
            ]
            try:
                subprocess.run(
                    command, capture_output=True, timeout=PATIENCE, check=False
                )
            except subprocess.TimeoutExpired:
                pass
            except OSError:
                return shots
        if out.exists() and out.stat().st_size > 1000:
            shots.append(Shot(width=name, path=out))
    return shots
