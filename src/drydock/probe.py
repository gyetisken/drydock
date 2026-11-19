"""What a browser can say about a page without anybody looking at it.

Most of what people mean by "test the interface" is not a matter of
opinion. A stylesheet that 404s, a script that threw on load, an image
that never arrived, a button with no accessible name, text at a contrast
nobody can read, a page that renders at 980 pixels on a phone because
nothing told it not to - every one of those is a fact the browser already
knows and will hand over if asked.

So this asks. It is the same Chrome and the same protocol the screenshots
and the overflow measurement already use, and it changes nothing: it
loads a page, reads what is there, and reports.

What is deliberately not here is judgement. Whether the thing looks right
is a different question with a different kind of answer, and mixing the
two is how a report that is mostly measurement comes to be read as mostly
opinion - or worse, the other way round.

Fails open, like the overflow check: a missing browser, a missing Node, a
page that will not load are each a check that did not happen, reported as
such rather than as a page that failed.
"""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .shot import find_browser

# The same six lines of plumbing both scripts need: start a headless
# Chrome, find the port it printed, open a socket to it, and get a session
# attached to a page. Kept once rather than twice, because the pair of them
# drifting apart is how one of them quietly stops emulating a phone.
CONNECT = r"""
const { spawn } = await import('node:child_process');
const { mkdtempSync } = await import('node:fs');
const chrome = spawn(process.env.DRYDOCK_BROWSER, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--remote-debugging-port=0', `--window-size=${width},1200`,
  '--user-data-dir=' + mkdtempSync('/tmp/drydock-probe-'), 'about:blank',
]);
const done = (value) => { console.log(value); chrome.kill(); process.exit(0); };
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
const heard = [];
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); return; }
  heard.push(m);
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
"""

CLICK = (
    r"""
const [, , target, widthArg] = process.argv;
const width = Number(widthArg);
"""
    + CONNECT
    + r"""
setTimeout(() => done(JSON.stringify({ error: 'the browser did not answer' })), 90000);
await send('Runtime.enable', {}, sessionId);
await send('Page.enable', {}, sessionId);

const go = async (url) => {
  await send('Page.navigate', { url }, sessionId);
  await new Promise((r) => setTimeout(r, 2200));
};
const ask = async (expression) => {
  const out = await send('Runtime.evaluate',
    { returnByValue: true, expression }, sessionId);
  return out.result && out.result.result && out.result.result.value;
};

await go(target);

// Only what is safe to press. A link that leaves for somewhere else is a
// request to the internet made on somebody's behalf, and a new tab is a
// browser this never gets back. Those are listed as skipped rather than
// pressed, because "not pressed" and "pressed and did nothing" are
// different findings.
const found = await ask(`(() => {
  const here = location.origin;
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('button, a[href], [role=button]')) {
    const said = ((el.innerText || el.textContent || '').trim() || '(no text)')
      .slice(0, 50);
    const href = el.getAttribute('href') || '';
    const key = said + '|' + href;
    if (seen.has(key)) continue;
    seen.add(key);
    let why = '';
    if (el.getAttribute('target') === '_blank') why = 'it opens a new tab';
    else if (/^(mailto|tel|sms):/i.test(href)) why = 'it hands off to another app';
    else if (href && !href.startsWith('#') && !href.startsWith('/')
             && !href.startsWith(here) && /^[a-z]+:/i.test(href))
      why = 'it leaves this site';
    out.push({ said, href, why });
  }
  return out.slice(0, 14);
})()`);

const before = async () => await ask(`JSON.stringify({
  url: location.href, y: Math.round(scrollY),
  size: document.body.innerHTML.length,
})`);

const pressed = [];
for (const one of found) {
  if (one.why) { pressed.push({ ...one, did: 'not pressed' }); continue; }

  const was = JSON.parse(await before());
  const spot = await ask(`(() => {
    const all = [...document.querySelectorAll('button, a[href], [role=button]')];
    const el = all.find(e => (((e.innerText || e.textContent || '').trim()
      || '(no text)').slice(0, 50)) === ${JSON.stringify(one.said)}
      && (e.getAttribute('href') || '') === ${JSON.stringify(one.href)});
    if (!el) return null;
    el.scrollIntoView({ block: 'center' });
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return { hidden: true };
    return { x: Math.round(r.left + r.width / 2),
             y: Math.round(r.top + r.height / 2) };
  })()`);

  if (!spot) { pressed.push({ ...one, did: 'was not there any more' }); continue; }
  if (spot.hidden) { pressed.push({ ...one, did: 'is there but has no size' }); continue; }

  const from = heard.length;
  // A real press at a real place, not el.click(): an element covered by
  // something else is a bug, and only a press at coordinates finds it.
  for (const type of ['mousePressed', 'mouseReleased']) {
    await send('Input.dispatchMouseEvent',
      { type, x: spot.x, y: spot.y, button: 'left', clickCount: 1 }, sessionId);
  }
  await new Promise((r) => setTimeout(r, 900));

  const threw = heard.slice(from)
    .filter(m => m.method === 'Runtime.exceptionThrown')
    .map(m => (m.params.exceptionDetails.exception || {}).description
              || m.params.exceptionDetails.text);
  const now = JSON.parse(await before());
  const moved = now.url !== was.url ? 'went to ' + now.url.slice(0, 80)
    : now.y !== was.y ? 'moved the page'
    : now.size !== was.size ? 'changed the page'
    : 'did nothing';
  pressed.push({ ...one, did: moved, threw: threw.slice(0, 2) });

  if (now.url !== was.url) await go(target);
}

done(JSON.stringify({ pressed }));
"""
)

LOOK = r"""
const [, , target, widthArg] = process.argv;
const width = Number(widthArg);
const { spawn } = await import('node:child_process');
const { mkdtempSync } = await import('node:fs');

const chrome = spawn(process.env.DRYDOCK_BROWSER, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  '--remote-debugging-port=0', `--window-size=${width},1200`,
  '--user-data-dir=' + mkdtempSync('/tmp/drydock-probe-'), 'about:blank',
]);

const done = (value) => { console.log(value); chrome.kill(); process.exit(0); };
setTimeout(() => done(JSON.stringify({ error: 'the browser did not answer' })), 30000);

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
const failed = [];
const thrown = [];
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); return; }
  // Collected as they arrive rather than asked for afterwards: a request
  // that failed and an exception that was thrown both happen during the
  // load and are gone by the time anybody asks.
  if (m.method === 'Network.loadingFailed' && !m.params.canceled) {
    failed.push({ what: m.params.type, why: m.params.errorText,
                  id: m.params.requestId });
  }
  if (m.method === 'Network.responseReceived' && m.params.response.status >= 400) {
    // Not the favicon. The browser asks for it whether or not the page
    // mentions one, so reporting it says nothing about the page and says
    // it on every single page.
    if (!/\/favicon\.ico(\?|$)/.test(m.params.response.url)) {
      failed.push({ what: m.params.type, why: 'HTTP ' + m.params.response.status,
                    url: m.params.response.url });
    }
  }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails;
    thrown.push((d.exception && d.exception.description) || d.text);
  }
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
await send('Network.enable', {}, sessionId);
await send('Runtime.enable', {}, sessionId);
await send('Page.enable', {}, sessionId);
await send('Page.navigate', { url: target }, sessionId);
await new Promise((r) => setTimeout(r, 3500));

// Two things about the text below, both because it is a template literal
// and not a file. Every backslash in it is doubled on purpose. This is a template
// literal, and a template literal eats one: `/\s+/` written singly
// arrives in the page as `/s+/`, which splits on the letter s and counts
// nothing. It looked like it worked - a page of a hundred words
// measured as sixteen, and the colour parser silently returned null for
// everything, so the contrast check reported a clean page it had never
// looked at. And there are no backticks in it at all, comments included:
// one in the words "a tel: link" closed the literal and the whole script
// stopped compiling.
const out = await send('Runtime.evaluate', {
  returnByValue: true,
  expression: `(() => {
    const seen = [];

    // Contrast, as arithmetic. The relative luminance of two colours gives
    // a ratio, and WCAG puts the line at 4.5 for ordinary text and 3 for
    // large text. Nobody has to squint at a screenshot to work this out.
    const lum = (c) => {
      const [r, g, b] = c.map(v => {
        v /= 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const rgb = (said) => {
      const n = (said.match(/[\\d.]+/g) || []).map(Number);
      return n.length >= 3 ? n.slice(0, 3) : null;
    };
    const behind = (el) => {
      // The nearest ancestor that actually paints something. A transparent
      // background is not a background, and reading one as white is how a
      // page on a dark ground is reported as perfectly legible.
      for (let at = el; at; at = at.parentElement) {
        const c = rgb(getComputedStyle(at).backgroundColor);
        const a = (getComputedStyle(at).backgroundColor.match(/[\\d.]+/g) || [])[3];
        if (c && (a === undefined || Number(a) > 0.5)) return c;
      }
      return [255, 255, 255];
    };

    const text = [...document.querySelectorAll('body *')].filter(el => {
      if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') return false;
      const own = [...el.childNodes].some(
        n => n.nodeType === 3 && n.textContent.trim().length > 2);
      return own;
    });

    const unreadable = [];
    for (const el of text.slice(0, 400)) {
      const style = getComputedStyle(el);
      const ink = rgb(style.color);
      if (!ink) continue;
      const size = parseFloat(style.fontSize);
      const bold = Number(style.fontWeight) >= 700;
      const large = size >= 24 || (size >= 18.66 && bold);
      const a = lum(ink), b = lum(behind(el));
      const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      if (ratio < (large ? 3 : 4.5)) {
        unreadable.push({
          what: el.tagName.toLowerCase(),
          said: el.textContent.trim().slice(0, 60),
          ratio: Math.round(ratio * 100) / 100,
          needs: large ? 3 : 4.5,
        });
      }
    }

    const images = [...document.images]
      .filter(i => !i.complete || i.naturalWidth === 0)
      .map(i => i.getAttribute('src') || '(no src)');

    // A control nobody can name is a control a screen reader reads as
    // "button", and a link to nowhere looks like a link.
    const nameless = [];
    for (const el of document.querySelectorAll(
      'button, a, input, select, textarea, [role=button], [role=link]')) {
      const name = (el.getAttribute('aria-label') || el.textContent || '')
        .trim() || el.getAttribute('title') || el.getAttribute('alt') || '';
      const href = el.getAttribute('href');
      if (!name) {
        nameless.push({ what: el.tagName.toLowerCase(), why: 'has no name' });
      } else if (el.tagName === 'A' && (href === null || href === '#' || href === '')) {
        nameless.push({ what: name.slice(0, 40), why: 'is a link to nowhere' });
      }
    }

    // What is on the page, as facts rather than as a picture. Anything
    // asked about the page later is answered out of these and has to
    // quote them, which is what keeps the answer checkable.
    const texts = (el) => [...document.querySelectorAll(el)]
      .map(e => (e.innerText || e.textContent || '').trim())
      .filter(t => t && t.length < 200);

    // Where a link actually goes, not only what it says. Without this,
    // "there is a phone number you can tap" cannot be settled: the number
    // is plainly in the text and whether it is a tel: link is the
    // question. (No backticks in here - see the note above the template.)
    const going = [...document.querySelectorAll('a[href]')]
      .map(a => ({
        said: (a.innerText || a.textContent || '').trim().slice(0, 60),
        to: a.getAttribute('href').slice(0, 120),
      }))
      .filter(l => l.said || l.to)
      .slice(0, 40);

    const rows = [...document.querySelectorAll('table')].map(t => ({
      what: 'table',
      rows: t.querySelectorAll('tr').length,
      said: (t.innerText || '').trim().slice(0, 300),
    })).concat([...document.querySelectorAll('ul, ol, dl')].map(l => ({
      what: l.tagName.toLowerCase(),
      rows: l.querySelectorAll('li, dt').length,
      said: (l.innerText || '').trim().slice(0, 300),
    })));

    return {
      text: (document.body.innerText || '').trim().slice(0, 6000),
      headings: texts('h1, h2, h3, h4'),
      links: texts('a, button').slice(0, 40),
      going,
      lists: rows.slice(0, 20),
      title: document.title || '',
      viewport: !!document.querySelector('meta[name="viewport"]'),
      visible: document.querySelectorAll('body *').length,
      words: (document.body.innerText || '').trim().split(/\\s+/).filter(Boolean).length,
      unreadable: unreadable.slice(0, 12),
      images,
      nameless: nameless.slice(0, 12),
      controls: document.querySelectorAll('button, a, input, select').length,
    };
  })()`,
}, sessionId);

const found = (out.result && out.result.result && out.result.result.value) || {};
done(JSON.stringify({ ...found, failed: failed.slice(0, 12), thrown: thrown.slice(0, 6) }));
"""


@dataclass
class Looked:
    """What the browser said, and nothing anybody decided."""

    width: int
    title: str = ""
    viewport: bool = True
    visible: int = 0
    words: int = 0
    controls: int = 0
    # What the page says, for anything asked about it afterwards.
    text: str = ""
    headings: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    going: list[dict] = field(default_factory=list)
    lists: list[dict] = field(default_factory=list)
    unreadable: list[dict] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    nameless: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    thrown: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ran(self) -> bool:
        return not self.error

    @property
    def blank(self) -> bool:
        """Nothing on it. A page that loads and shows nothing is the one
        failure a screenshot catches easily and a test suite never does."""
        return self.ran and self.words < 3 and self.visible < 5

    def breaking(self) -> list[str]:
        """The findings that mean this page is not working.

        Kept apart from the rest because of where they are used. During a
        run these send an item back, and sending one back costs an attempt
        - so only the things that mean the page does not work belong here:
        a script that threw, something that did not load, nothing rendered
        at all.

        Contrast, a control with no name, a missing viewport tag are all
        real and none of them is this item being broken. They are reported
        and handed to whoever looks next, rather than spending an attempt.
        """
        if not self.ran:
            return []
        said = []
        for why in self.thrown:
            said.append(f"a script threw on load: {why.splitlines()[0][:120]}")
        for f in self.failed:
            said.append(
                f"a {f.get('what', 'request')} did not load "
                f"({f.get('why', 'unknown')}){_at(f.get('url'))}"
            )
        if self.blank:
            said.append(
                f"the page is blank: {self.words} words and "
                f"{self.visible} elements rendered into the body"
            )
        named = " ".join(str(f.get("url", "")) for f in self.failed)
        for src in self.images:
            if src.split("/")[-1] and src.split("/")[-1] in named:
                continue
            said.append(f"an image did not load: {src[:80]}")
        return list(dict.fromkeys(said))

    def worth_saying(self) -> list[str]:
        """Everything else - true, and not worth an attempt on its own."""
        breaking = set(self.breaking())
        return [f for f in self.findings() if f not in breaking]

    def findings(self) -> list[str]:
        """Everything wrong with it, said once each."""
        if not self.ran:
            return []
        said = []
        for why in self.thrown:
            said.append(f"a script threw on load: {why.splitlines()[0][:120]}")
        for f in self.failed:
            said.append(
                f"a {f.get('what', 'request')} did not load "
                f"({f.get('why', 'unknown')}){_at(f.get('url'))}"
            )
        if self.blank:
            said.append("the page is blank: nothing was rendered into the body")
        if not self.viewport:
            said.append(
                "there is no viewport meta tag, so a phone renders this at "
                "980px and scales it down - which is why it can measure as "
                "fitting when it does not"
            )
        # Only the ones the network did not already account for. An image
        # that 404s arrives twice - once as a request that failed and once
        # as an image that never completed - and saying it twice makes a
        # report look longer than the thing is wrong.
        named = " ".join(str(f.get("url", "")) for f in self.failed)
        for src in self.images:
            if src.split("/")[-1] and src.split("/")[-1] in named:
                continue
            said.append(f"an image did not load: {src[:80]}")
        for n in self.nameless:
            said.append(f"{n['what']} {n['why']}")
        for u in self.unreadable:
            said.append(
                f"text is below the contrast anybody can read: "
                f'"{u["said"]}" is {u["ratio"]}:1 and needs {u["needs"]}:1'
            )
        # Once each, in the order they were found. The same failure can
        # arrive down two channels - a document that will not load is both
        # a request that failed and a navigation that did - and a report
        # that says it twice reads as twice as much wrong.
        return list(dict.fromkeys(said))


@dataclass
class Pressed:
    """One control, and what happened when it was pressed."""

    said: str
    href: str = ""
    did: str = ""
    why: str = ""
    threw: list[str] = field(default_factory=list)

    @property
    def tried(self) -> bool:
        return self.did != "not pressed"

    @property
    def wrong(self) -> str:
        """What is worth saying about it, or nothing."""
        if not self.tried:
            return ""
        if self.threw:
            return f'"{self.said}" threw when pressed: {self.threw[0][:100]}'
        if self.did == "did nothing":
            return f'"{self.said}" does nothing when pressed'
        if self.did == "is there but has no size":
            return f'"{self.said}" is on the page with no size, so nobody can press it'
        if self.did == "was not there any more":
            return f'"{self.said}" vanished between being found and being pressed'
        return ""


def press(url: str, width: int = 1440, timeout: int = 120) -> list[Pressed]:
    """Press what is safe to press, and report what happened.

    What this establishes is that a control does *something* - the page
    moved, the page changed, the address changed. What it cannot
    establish is that it did the right thing, which needs somebody to
    have said what the right thing is.

    What it will not do is leave the site. A link to somewhere else is a
    request made to the internet on somebody's behalf, and a new tab is a
    browser this never gets back - so those are reported as not pressed,
    which is a different finding from pressed and nothing happened.
    """
    browser = find_browser()
    if not browser or not shutil.which("node"):
        return []

    with tempfile.TemporaryDirectory(prefix="drydock-press-") as scratch:
        script = Path(scratch) / "press.mjs"
        script.write_text(CLICK)
        try:
            done = subprocess.run(
                ["node", str(script), url, str(width)],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**_env(), "DRYDOCK_BROWSER": browser},
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []

    said = (done.stdout or "").strip().splitlines()
    if not said:
        return []
    try:
        found = json.loads(said[-1])
    except ValueError:
        return []
    return [
        Pressed(
            said=one.get("said", ""),
            href=one.get("href", ""),
            did=one.get("did", ""),
            why=one.get("why", ""),
            threw=one.get("threw") or [],
        )
        for one in found.get("pressed") or []
    ]


def _at(url: str | None) -> str:
    return f" - {url[-60:]}" if url else ""


def look(url: str, width: int = 390, timeout: int = 45) -> Looked:
    """Load a page and report what the browser knows about it."""
    browser = find_browser()
    if not browser:
        return Looked(width=width, error="there is no browser on this machine")
    if not shutil.which("node"):
        return Looked(width=width, error="there is no node on this machine")

    with tempfile.TemporaryDirectory(prefix="drydock-probe-") as scratch:
        script = Path(scratch) / "look.mjs"
        script.write_text(LOOK)
        try:
            done = subprocess.run(
                ["node", str(script), url, str(width)],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**_env(), "DRYDOCK_BROWSER": browser},
                # A non-zero exit is a check that did not happen, read from
                # what it printed, not an exception thrown at the caller.
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return Looked(width=width, error=f"the page would not answer: {exc}")

    said = (done.stdout or "").strip().splitlines()
    if not said:
        return Looked(width=width, error="the browser said nothing")
    try:
        found = json.loads(said[-1])
    except ValueError:
        return Looked(width=width, error=f"the browser said: {said[-1][:120]}")
    if found.get("error"):
        return Looked(width=width, error=found["error"])
    return Looked(width=width, **{k: v for k, v in found.items() if k != "error"})


def _env() -> dict:
    import os

    return dict(os.environ)
