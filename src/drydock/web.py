"""The application.

Two screens. The home screen is where a job is started: pick a project, type a
command, read what it is about to do. The run screen is where one job is
watched. Everything else is an endpoint those two call.
"""

import queue
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .commands import available, match
from .repo import Repo
from .run import Run
from .skills import load as load_skill
from .workspace import Workspace

app = FastAPI(title="drydock")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SKILLS = Path("skills")
workspace = Workspace().load()


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>drydock</title><link rel="stylesheet" href="/static/app.css"></head>
<body><div class="app">

  <aside>
    <div class="brand">
      <svg class="mark" viewBox="0 0 64 64" aria-hidden="true">
        <rect width="64" height="64" rx="15" fill="var(--markbg)"/>
        <path d="M15 21 H49 L42 41 H22 Z" fill="none" stroke="var(--accent)"
          stroke-width="4.2" stroke-linejoin="round"/>
        <path d="M23 30 l 6.5 7.5 L 46 17" fill="none" stroke="var(--markink)"
          stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M26 47 h12" stroke="var(--accent)" stroke-width="3.4"
          stroke-linecap="round" opacity=".55"/>
      </svg>
      <span class="wordmark"><b>drydock</b><i>starts new projects and changes existing ones</i></span>
    </div>

    <button class="sidebar-toggle" id="collapse" title="hide the sidebar (&#8984;B)">&#8249;</button>

    <div class="side-h">Projects <button id="plus" title="add a repository">+</button></div>
    <div class="addbox" id="addbox">
      <input id="newpath" placeholder="/path/to/a/git/repository" spellcheck="false">
      <div class="row">
        <button class="btn small" id="add">Add</button>
        <button class="btn small ghost" id="cancel">Cancel</button>
      </div>
    </div>
    <div class="side-list" id="projects"></div>

    <div class="side-h">Earlier
      <input id="find" placeholder="filter" spellcheck="false"></div>
    <div class="side-list grow" id="history"></div>

    <button class="account" id="open-settings">
      <span class="dot" id="acct-dot"></span>
      <span class="who"><b id="acct">checking your account</b><i id="acct-sub"></i></span>
      <span class="gear">&#9881;</span>
    </button>
  </aside>

  <main>
    <div class="topbar">
      <b id="proj">no project</b><span class="sub" id="chain"></span>
      <div class="right">
        <span class="running" id="running" style="display:none">
          <span class="pulse"></span><b id="running-what">working</b>
          <i id="clock">0:00</i>
        </span>
        <div class="segmented tabs" id="views">
          <button data-view="thread" class="on">Thread</button>
          <button data-view="office">Office</button>
        </div>
        <span id="spend"></span>
      </div>
    </div>

    <div class="thread" id="thread">
      <div class="inner" id="thread-inner">
        <div class="msg"><div class="body">
          <p>Pick a project on the left, then type a command. <code>/</code> shows
          what the crew can do.</p>
          <p class="why">Work happens on its own branch, one item at a time. Each
          item has to leave the test suite at least as healthy as it found it, and
          one that does not is rolled back before the next begins. Nothing is
          changed until you approve the plan.</p>
        </div></div>
      </div>
    </div>

    <div class="office" id="office" style="display:none">
      <div class="floor">
        <div class="room" id="room"></div>
        <div class="legend">
          <div class="who-list" id="who-list"></div>
          <div class="shelf">
            <span class="shelf-h">Skills on the shelf</span>
            <span class="shelf-items" id="shelf"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="composer"><div class="cwrap">
      <div class="menu" id="menu" style="display:none"></div>
      <div class="cbox">
        <textarea id="box" rows="1" placeholder="/ to see commands" spellcheck="false"></textarea>
        <div class="picks">
          <button class="pick" id="pick-model">
            <span id="model-label">Opus</span><span class="caret">&#9662;</span>
          </button>
          <button class="pick ghost" id="pick-engine">
            <span id="engine-label">Claude</span><span class="caret">&#9662;</span>
          </button>
          <button class="go" id="go" title="send"><span id="go-icon">&#8593;</span></button>
        </div>
        <div class="pop" id="pop-model" style="display:none"></div>
        <div class="pop right" id="pop-engine" style="display:none"></div>
      </div>
      <div class="hint" id="hint"></div>
    </div></div>
  </main>

</div>

<div class="ctx" id="ctx" style="display:none"></div>

<div class="palette" id="palette" style="display:none">
  <div class="pal-bg" id="pal-bg"></div>
  <div class="pal-card">
    <input id="pal-q" placeholder="Search projects, commands and past runs" spellcheck="false">
    <div class="pal-list" id="pal-list"></div>
    <div class="pal-foot">
      <span><kbd>&#8593;</kbd><kbd>&#8595;</kbd> move</span>
      <span><kbd>&#8629;</kbd> choose</span>
      <span><kbd>esc</kbd> close</span>
      <span class="right">&#8984;K anywhere &middot; ? for shortcuts</span>
    </div>
  </div>
</div>

<div class="sheet" id="keys" style="display:none">
  <div class="sheet-bg" data-close-keys></div>
  <div class="sheet-card narrow">
    <div class="sheet-top"><b>Keyboard</b>
      <button class="btn small ghost" data-close-keys>Close</button></div>
    <section><div class="keys" id="keys-list"></div></section>
  </div>
</div>

<div class="sheet" id="sheet" style="display:none">
  <div class="sheet-bg" id="sheet-bg"></div>
  <div class="sheet-card">
    <div class="sheet-top">
      <b>Settings</b>
      <button class="btn small ghost" id="close-settings">Close</button>
    </div>

    <section>
      <h4>Your Claude account</h4>
      <div class="kv" id="acct-detail"></div>
      <p class="why">drydock runs the crew through the Claude Code command line,
      so the work is billed to whatever plan you are already signed in to.
      There is no API key to paste and no second bill. Signing in or out is done
      with <code>claude login</code> in a terminal.</p>
    </section>

    <section>
      <h4>What this has cost</h4>
      <div class="stats" id="use-stats"></div>
      <div class="save" id="save-box"></div>
    </section>

    <section>
      <h4>Appearance</h4>
      <div class="segmented" id="theme">
        <button data-theme="system">Match system</button>
        <button data-theme="light">Light</button>
        <button data-theme="dark">Dark</button>
      </div>
    </section>

    <section>
      <h4>GitHub</h4>
      <div class="kv" id="gh-detail"></div>
      <p class="why" id="gh-why"></p>
    </section>
  </div>
</div>

<script src="/static/keys.js"></script>
<script src="/static/office.js"></script>
<script src="/static/palette.js"></script>
<script src="/static/chat.js"></script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(PAGE)


MODELS = [
    {"id": "opus", "label": "Opus", "note": "most capable, slowest, dearest"},
    {"id": "sonnet", "label": "Sonnet", "note": "the sensible default"},
    {"id": "haiku", "label": "Haiku", "note": "fast and cheap, for simple work"},
]


def _usage() -> dict:
    """What has been spent, and what was spent on a plan rather than a bill.

    Two different savings are worth reporting and they must not be added
    together, because they are not the same kind of money:

      covered  work that ran on a Claude subscription. The engine reports what
               the same tokens would have cost through the API, and on a plan
               that amount is simply not charged.
      routing  work that did go through the API, where cheap models did the
               looking up and the expensive one did the deciding. Pricing the
               same tokens at Opus rates gives the bill for not having done
               that. Only API runs have token counts, so only they appear.
    """
    runs = workspace.history(limit=200)
    billed = covered = at_opus = routed = 0.0
    for run in runs:
        if run.engine == "claude":
            covered += run.cost
        else:
            billed += run.cost
            if run.as_opus:
                at_opus += run.as_opus
                routed += run.cost
    landed = sum(sum(1 for x in r.results if x.outcome.value == "done") for r in runs)
    return {
        "runs": len(runs),
        "items": landed,
        "billed": round(billed, 2),
        "covered": round(covered, 2),
        "at_opus": round(at_opus, 2),
        "routed": round(routed, 2),
        "routing_saved": round(max(0.0, at_opus - routed), 2),
        "per_item": round((billed + covered) / landed, 2) if landed else 0.0,
    }


def _account() -> dict:
    """Who the Claude command line is signed in as, if it is.

    There is no supported way to ask Claude Code for the signed-in identity, so
    this reports only what can be known for certain: whether the binary exists,
    whether it answers, and which plan the credentials file says it is on. When
    something cannot be known it says so rather than guessing a name.
    """
    import json
    import shutil
    import subprocess

    binary = shutil.which("claude")
    if not binary:
        return {
            "signed_in": False,
            "headline": "Claude Code not installed",
            "sub": "install it to use your own plan",
            "plan": "",
            "version": "",
        }

    version = ""
    try:
        version = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        version = f"could not ask: {exc}"

    # The signed-in identity is not something Claude Code exposes on purpose,
    # so this reads the account record it keeps beside its own settings. Only
    # the display name and the plan are used; nothing is sent anywhere.
    who: dict = {}
    try:
        settings = Path.home() / ".claude.json"
        if settings.exists():
            who = json.loads(settings.read_text()).get("oauthAccount") or {}
    except Exception:  # noqa: BLE001
        who = {}

    plan = str(who.get("subscriptionType") or "")
    if not plan and who.get("billingType") == "stripe_subscription":
        plan = "subscription"
    name = str(who.get("displayName") or who.get("emailAddress") or "")

    signed_in = bool(who)
    return {
        "signed_in": signed_in,
        "headline": name or ("Claude Code ready" if signed_in else "Not signed in"),
        "sub": f"{plan} plan · work is billed to it"
        if signed_in
        else "run claude login",
        "plan": plan,
        "email": str(who.get("emailAddress") or ""),
        "org": str(who.get("organizationName") or ""),
        "version": version,
    }


def _github() -> dict:
    """Whether a GitHub login is available for pushing branches and opening PRs."""
    import shutil
    import subprocess

    binary = shutil.which("gh")
    if not binary:
        return {
            "ready": False,
            "user": "",
            "note": "The GitHub command line is not installed. drydock works "
            "without it: changes land on a local branch either way. Installing "
            "gh lets a finished run be pushed and opened as a pull request.",
        }
    try:
        out = subprocess.run(
            [binary, "api", "user", "-q", ".login"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ready": False, "user": "", "note": str(exc)}
    user = out.stdout.strip()
    if out.returncode or not user:
        return {
            "ready": False,
            "user": "",
            "note": "gh is installed but not signed in. Run gh auth login in a "
            "terminal to connect an account.",
        }
    return {
        "ready": True,
        "user": user,
        "note": "A finished branch can be pushed and opened as a pull request "
        "under this account.",
    }


@app.get("/api/settings")
def settings() -> dict:
    return {"account": _account(), "github": _github(), "usage": _usage()}


@app.get("/api/usage")
def usage() -> dict:
    return _usage()


def _engines() -> list[dict]:
    """Which ways of running the crew are actually available here."""
    import os
    import shutil

    return [
        {
            "id": "claude",
            "short": "Your plan",
            "label": "Your Claude account",
            "detail": "runs through Claude Code, signed in as you",
            "ready": bool(shutil.which("claude")),
            "why": "Claude Code is not installed on this machine",
        },
        {
            "id": "api",
            "short": "API key",
            "label": "An API key",
            "detail": "billed per token, with a hard budget per run",
            "ready": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "why": "ANTHROPIC_API_KEY is not set",
        },
    ]


@app.get("/api/state")
def state() -> dict:
    return {
        "projects": [
            {
                "path": str(p.path),
                "name": p.name,
                "folder": p.path.name,
                "pinned": p.pinned,
                "toolchain": p.toolchain(),
                "last_used": p.last_used,
                "ok": p.exists,
            }
            for p in workspace.projects
        ],
        "engines": _engines(),
        "models": MODELS,
        "usage": _usage(),
        "commands": [
            {
                "name": c.name,
                "summary": c.summary,
                "asks": c.asks,
                "stages": c.stages,
                "skill": c.skill.name if c.skill else None,
            }
            for c in available(SKILLS)
        ],
        "runs": [
            {
                "id": r.id,
                "task": r.task,
                "repo": Path(r.repo).name,
                "items": len(r.plan.items) if r.plan else 0,
                "done": sum(1 for x in r.results if x.outcome.value == "done"),
                "cost": round(r.cost, 2),
                "started": r.started[:16].replace("T", " "),
            }
            for r in workspace.history()
        ],
    }


class AddProject(BaseModel):
    path: str


@app.post("/api/projects")
def add_project(body: AddProject) -> JSONResponse:
    try:
        project = workspace.add_project(Path(body.path))
    except ValueError as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "name": project.name})


@app.delete("/api/projects")
def forget_project(body: AddProject) -> dict:
    """Take a project off the list. The folder on disk is not touched.

    Nothing here deletes anyone's work. Removing a repository from a sidebar
    is a filing decision, and a program that reads it as permission to delete
    a directory has made a much larger decision on somebody's behalf.
    """
    workspace.forget(body.path)
    return {"ok": True}


class EditProject(BaseModel):
    path: str
    label: str | None = None
    pinned: bool | None = None


@app.patch("/api/projects")
def edit_project(body: EditProject) -> dict:
    if body.label is not None:
        workspace.rename(body.path, body.label)
    if body.pinned is not None:
        workspace.pin(body.path, body.pinned)
    return {"ok": True}


class StartJob(BaseModel):
    project: str
    command: str
    budget: float = 4.0
    engine: str = "claude"
    model: str = "opus"


@app.post("/api/start")
def start(body: StartJob) -> JSONResponse:
    commands = available(SKILLS)
    command, rest = match(body.command, commands)
    if command is None:
        return JSONResponse(
            {"ok": False, "reason": "unknown command. Type / to see the list."},
            status_code=400,
        )
    if command.asks and not rest:
        return JSONResponse(
            {"ok": False, "reason": f"{command.name} needs {command.asks}"},
            status_code=400,
        )

    skills = [load_skill(command.skill)] if command.skill else []
    session = workspace.start(
        Path(body.project),
        command.task_for(rest),
        skills,
        body.budget,
        body.engine,
        body.model,
        command.stop_after,
    )
    key = next(k for k, v in workspace.sessions.items() if v is session)
    return JSONResponse({"ok": True, "key": key})


@app.get("/api/diff/{run_id}/{item_id}")
def item_diff(run_id: str, item_id: int) -> dict:
    """The change one item made, read back out of the repository.

    Not stored with the run: the commit is the record, and a copy of it kept
    somewhere else is a copy that can disagree with the repository.
    """
    try:
        run = Run.load(run_id)
    except (OSError, ValueError):
        return {"ok": False, "reason": "no such run"}

    result = next((r for r in run.results if r.item.id == item_id), None)
    if result is None:
        return {"ok": False, "reason": "no such item in that run"}
    if not result.commit:
        return {
            "ok": False,
            "reason": "this item was rolled back, so there is no commit to show",
        }

    patch = Repo(Path(run.repo)).show(result.commit)
    return {
        "ok": True,
        "commit": result.commit[:10],
        "title": result.item.title,
        "patch": patch[:120_000],
        "clipped": len(patch) > 120_000,
    }


@app.post("/api/stop/{key}")
def stop(key: str) -> dict:
    session = workspace.session_for(key)
    if session is None:
        return {"ok": False, "reason": "no such run"}
    session.stop()
    return {"ok": True}


@app.get("/api/stream/{key}")
async def stream(key: str, request: Request) -> StreamingResponse:
    session = workspace.session_for(key)
    if session is None:
        return JSONResponse({"ok": False, "reason": "no such run"}, status_code=404)
    listener = session.feed.listen()

    async def pump():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = listener.get(timeout=1.0)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield event.sse()
        finally:
            session.feed.stop_listening(listener)

    return StreamingResponse(
        pump(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/approve/{key}")
def approve(key: str) -> dict:
    session = workspace.session_for(key)
    if session is None or session.run is None or session.run.plan is None:
        return {"ok": False, "reason": "there is no plan to approve yet"}
    session.approve()
    return {"ok": True}
