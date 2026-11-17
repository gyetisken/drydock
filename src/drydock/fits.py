"""Whether the page fits the screen it is on.

Seven items in one afternoon were refused for the same thing: text running
off the right edge of a phone, cut mid-word. Every time the engineer was
told, in detail, and every time it changed something else - because it
cannot look at the page. Being told is the only thing it has, and a rule
in prose had already been added and was already reaching it.

So this stops being a matter of judgement. A page that is wider than the
screen is arithmetic: `scrollWidth` against `clientWidth`, which the
browser will answer directly. It needs no library - Chrome is already here
for the critic, and Node, which every project this applies to already has,
can speak to it.

Fails open on purpose. A missing browser, a missing Node, a page that will
not load: each is a check that did not happen, reported as such, rather
than an item refused for something this program could not measure.
"""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .shot import find_browser

# The widths that matter. The first is the narrowest phone anybody still
# carries; the second is where a desktop layout is usually designed and
# where nobody ever notices the problem.
WIDTHS = (390, 1440)

PROBE = r"""
const [, , target, widthArg] = process.argv;
const width = Number(widthArg);
const { spawn } = await import('node:child_process');
const { mkdtempSync } = await import('node:fs');

const chrome = spawn(process.env.DRYDOCK_BROWSER, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--remote-debugging-port=0', `--window-size=${width},1200`,
  '--user-data-dir=' + mkdtempSync('/tmp/drydock-fits-'), 'about:blank',
]);

const done = (value) => { console.log(value); chrome.kill(); process.exit(0); };
setTimeout(() => done(JSON.stringify({ error: 'the browser did not answer' })), 25000);

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
await send('Emulation.setDeviceMetricsOverride',
  { width, height: 1200, deviceScaleFactor: 1, mobile: width < 700 }, sessionId);
await send('Page.enable', {}, sessionId);
await send('Page.navigate', { url: target }, sessionId);
await new Promise((r) => setTimeout(r, 3500));

const out = await send('Runtime.evaluate', {
  returnByValue: true,
  expression: `(() => {
    const root = document.documentElement;
    const seen = root.clientWidth;
    const wide = [...document.querySelectorAll('body *')]
      .filter((el) => el.scrollWidth > el.clientWidth + 1
                   || el.getBoundingClientRect().right > seen + 1)
      .map((el) => el.tagName.toLowerCase()
        + (el.id ? '#' + el.id : '')
        + (typeof el.className === 'string' && el.className.trim()
            ? '.' + el.className.trim().split(/\s+/).join('.') : ''))
      .slice(0, 5);
    return JSON.stringify({ seen, needs: root.scrollWidth, wide });
  })()`,
}, sessionId);

done(out.result?.result?.value ?? JSON.stringify({ error: 'the page did not answer' }));
"""


@dataclass
class Fit:
    width: int
    seen: int = 0
    needs: int = 0
    wide: tuple[str, ...] = ()
    error: str = ""

    @property
    def fits(self) -> bool:
        # One pixel of slack: a rounded sub-pixel measure is not a defect.
        return bool(not self.error and self.needs <= self.seen + 1)


def _node() -> str:
    return shutil.which("node") or ""


def measure(url: str, width: int) -> Fit:
    """Ask the browser how wide the page needs to be at this width."""
    browser = find_browser()
    if not browser:
        return Fit(width=width, error="there is no browser on this machine")
    node = _node()
    if not node:
        return Fit(width=width, error="node is not on this machine")

    with tempfile.TemporaryDirectory(prefix="drydock-fits-") as scratch:
        probe = Path(scratch) / "probe.mjs"
        probe.write_text(PROBE)
        try:
            done = subprocess.run(
                [node, str(probe), url, str(width)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env={
                    "PATH": "/usr/bin:/bin:/usr/local/bin",
                    "DRYDOCK_BROWSER": browser,
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Fit(width=width, error=str(exc)[:200])

    line = (done.stdout or "").strip().splitlines()
    if not line:
        return Fit(
            width=width, error=(done.stderr or "nothing came back").strip()[-200:]
        )
    try:
        said = json.loads(line[-1])
    except ValueError:
        return Fit(width=width, error=line[-1][:200])
    if said.get("error"):
        return Fit(width=width, error=said["error"])
    return Fit(
        width=width,
        seen=int(said.get("seen") or 0),
        needs=int(said.get("needs") or 0),
        wide=tuple(said.get("wide") or ()),
    )


def why_it_does_not_fit(url: str, widths: tuple[int, ...] = WIDTHS) -> str:
    """A refusal, or empty when the page fits every width that matters.

    Deliberately says the numbers. "The page is 1187 pixels wide on a 390
    pixel screen" is something to go and measure; "text is cut off" has
    been said seven times and changed nothing.
    """
    complaints = []
    for width in widths:
        fit = measure(url, width)
        if fit.error or fit.fits:
            continue
        over = fit.needs - fit.seen
        said = (
            f"At {fit.width}px the page needs {fit.needs}px and has "
            f"{fit.seen}px, so {over}px of it is off the right of the "
            "screen and everything out there is unreadable."
        )
        if fit.wide:
            said += " Wider than the screen: " + ", ".join(fit.wide) + "."
        complaints.append(said)

    if not complaints:
        return ""
    return "\n".join(complaints) + (
        "\n\nNothing else about this item matters until the page fits. "
        "Find the element by its width rather than by reading: the one "
        "whose box is wider than the screen is the fault, and everything "
        "inside it inherits the problem."
    )
