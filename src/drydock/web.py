"""The application.

Two screens. The home screen is where a job is started: pick a project, type a
command, read what it is about to do. The run screen is where one job is
watched. Everything else is an endpoint those two call.
"""

import queue
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from . import crew, intent, preview, publish, version
from .commands import available, match
from .engines import stop_workers
from .pace import events_in
from .repo import GitError, Repo
from .run import Run
from .session import Session
from .settings import Settings
from .skills import load as load_skill
from .workspace import Workspace, where_projects_go

app = FastAPI(title="drydock")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _version() -> str:
    """A token that changes whenever the interface does.

    Without it a browser keeps yesterday's JavaScript against today's markup,
    and the result is not a stale page but a broken one: the HTML has elements
    the old script has never heard of, so half the room simply does not draw.
    It looked like a rendering bug and was a caching one. Nobody should have to
    know to hold shift while reloading.
    """
    newest = 0.0
    for path in STATIC.rglob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return str(int(newest))


SKILLS = Path("skills")
workspace = Workspace().load()


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>drydock</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/app.css"></head>
<body><div class="app">

  <aside>
    <div class="brand">
      <svg class="mark" viewBox="0 0 64 64" aria-hidden="true">
        <rect width="64" height="64" rx="15" fill="var(--markbg)"/>
        <g fill="var(--markink)"
           transform="translate(32 33) scale(.78) translate(-32 -32)">
          <path fill-rule="evenodd"
                d="M32 5 57 20.5 32 36 7 20.5Z
                   M22.8 20.8l2-2.1 5.2 4.8 10.3-9.6 2 2.2-12.3 11.4Z"/>
          <path d="M7 25.5 32 41 57 25.5 57 31.5 32 47 7 31.5Z"/>
          <path d="M7 36.5 32 52 57 36.5 57 42.5 32 58 7 42.5Z"/>
        </g>
      </svg>
      <span class="wordmark"><b>drydock</b><i>starts new projects and changes existing ones</i></span>
    </div>

    <button class="sidebar-toggle" id="collapse" title="hide the sidebar (&#8984;B)">&#8249;</button>

    <div class="version" id="version" hidden></div>

    <div class="side-h">Projects <button id="plus" title="add a repository">+</button></div>
    <div class="addbox" id="addbox">
      <input id="newpath" placeholder="a name, or /path/to/an/existing/repository"
             spellcheck="false">
      <div class="hint" id="wherebox"></div>
      <div class="row">
        <button class="btn small" id="add">Add</button>
        <button class="btn small ghost" id="cancel">Cancel</button>
      </div>
    </div>
    <div class="side-list" id="projects"></div>

    <div class="side-list grow" id="projects-rest"></div>

    <button class="account" id="open-settings">
      <span class="dot" id="acct-dot"></span>
      <span class="who"><b id="acct">checking your account</b><i id="acct-sub"></i></span>
      <span class="gear">&#9881;</span>
    </button>
  </aside>

  <main>
    <div class="topbar">
      <button id="show-side" title="show the sidebar (&#8984;B)">&#9776;</button>
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
        <button class="btn small ghost" id="toggle-preview"
          title="show the project as it is being built">Preview</button>
      </div>
    </div>

    <div class="thread" id="thread">
      <div class="inner" id="thread-inner"></div>
    </div>

    <div class="office" id="office" style="display:none">
      <div class="floor">
        <div class="room" id="room"></div>
        <div class="legend">
          <div class="who-list" id="who-list"></div>
          <div class="who-detail" id="who-detail" aria-live="polite"></div>
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
        <textarea id="box" rows="1"
          placeholder="Say what you want. / for the list if you prefer."
          spellcheck="false"></textarea>
        <div class="reading" id="reading" style="display:none">
          <span class="verb" id="reading-verb"></span>
          <span class="why" id="reading-why"></span>
          <button class="btn small ghost" id="reading-change">not that</button>
        </div>
        <div class="picks">
          <button class="pick" id="pick-model">
            <span id="model-label">Opus</span><span class="caret">&#9662;</span>
          </button>
          <label class="pick ghost limit" title="end the run after this many minutes, whatever it is doing">
            <input id="minutes" type="number" min="1" max="600" step="5"
                   placeholder="&#8734;" inputmode="numeric">
            <span>min</span>
          </label>
          <button class="go" id="go" title="send"><span id="go-icon">&#8593;</span></button>
        </div>
        <div class="pop" id="pop-model" style="display:none"></div>
      </div>
      <div class="hint" id="hint"></div>
    </div></div>
  </main>

  <section class="preview" id="preview" style="display:none">
    <div class="pv-bar">
      <span class="dot" id="pv-dot"></span>
      <input id="pv-url" readonly spellcheck="false">
      <button class="btn small ghost" id="pv-reload" title="reload">&#8635;</button>
      <button class="btn small ghost" id="pv-open" title="open in a tab">&#8599;</button>
      <button class="btn small ghost" id="pv-close" title="close">&times;</button>
    </div>
    <!-- What was actually observed, said separately. The server answering
         and the page being there are two facts and used to share one dot. -->
    <div class="pv-state" id="pv-state"></div>
    <div class="pv-body" id="pv-body">
      <p class="empty" id="pv-said">Nothing is running yet. This starts the
      project the way its own manifest says it starts, and reloads it each time
      an item lands.</p>
    </div>
  </section>

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
      <h4>When a run finishes</h4>
      <label class="choice">
        <input type="checkbox" id="auto-pr">
        <span><b>Open a draft pull request</b>
        <i>The only thing drydock does that leaves this machine. A draft, on
        the run's own branch, only when something landed, carrying what each
        gate said. Off, and the work is still on its branch.</i></span>
      </label>
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
    # Every asset the page pulls is stamped with the newest mtime under
    # static/, so one edit anywhere invalidates the lot and nothing can be
    # half a version behind.
    stamped = PAGE.replace('.css"', f'.css?v={_version()}"').replace(
        '.js"', f'.js?v={_version()}"'
    )
    return HTMLResponse(
        stamped,
        headers={"Cache-Control": "no-store"},
    )


MODELS = [
    {
        "id": "opus",
        "label": "Opus",
        "note": "decides and reviews; Sonnet does the typing",
    },
    {"id": "sonnet", "label": "Sonnet", "note": "Sonnet throughout"},
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
    return {
        "account": _account(),
        "github": _github(),
        "usage": _usage(),
        "choices": asdict(Settings.load()),
    }


class Choice(BaseModel):
    publish_when_done: bool


@app.patch("/api/settings")
def change_settings(body: Choice) -> dict:
    kept = Settings.load()
    kept.publish_when_done = body.publish_when_done
    kept.save()
    return {"ok": True, "choices": asdict(kept)}


@app.get("/api/usage")
def usage() -> dict:
    return _usage()


def _engines() -> list[dict]:
    """How the crew runs. There is one way and it is the subscription.

    There were two: the Claude Code CLI signed in as whoever is at the
    machine, and an API key billed per token. The second was removed
    because it bills on top of a plan that is already paid for - see
    `agent.OnTheSubscription`. It is still reported, so that a window
    built against the older shape does not break and so that somebody
    looking at the list can see it was not forgotten.
    """
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
    ]


@app.get("/api/state")
def state() -> dict:
    # Read once and hand out per project, rather than once per project.
    history = workspace.history(limit=400)
    return {
        # Which Drydock this is. A server keeps the code it started with,
        # so a fix that is in the repository and not in this process is a
        # fix that does not exist for the run in front of you.
        "version": version.status(),
        "projects": [
            {
                "path": str(p.path),
                "name": p.name,
                "folder": p.path.name,
                "pinned": p.pinned,
                "instructions": p.instructions,
                "runs": [
                    {
                        "id": r.id,
                        "task": r.task,
                        "items": len(r.plan.items) if r.plan else 0,
                        "done": sum(1 for x in r.results if x.outcome.value == "done"),
                        "cost": round(r.cost, 2),
                        "started": r.started[:16].replace("T", " "),
                        "answer": r.answer,
                        "unfinished": bool(
                            r.plan
                            and len(r.results) < len(r.plan.items)
                            and all(x.outcome.value == "done" for x in r.results)
                        ),
                    }
                    for r in history
                    if Path(r.repo) == p.path
                    # A run that never reached a plan and never spent anything
                    # did not happen. Keeping those turns the project's own
                    # history into the noise the global list used to be.
                    and (r.plan or r.cost or r.results or r.answer)
                ],
                "toolchain": p.toolchain(),
                "last_used": p.last_used,
                "ok": p.exists,
            }
            for p in workspace.projects
        ],
        "engines": _engines(),
        "projects_home": str(where_projects_go()),
        "crew": crew.as_rows(),
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
                # A plan with items that have no result at all was cut off
                # rather than finished. An item that was reverted has a
                # result, so a run that stopped because something failed is
                # finished, not unfinished.
                "unfinished": bool(
                    r.plan
                    and len(r.results) < len(r.plan.items)
                    and all(x.outcome.value == "done" for x in r.results)
                ),
            }
            for r in history
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
    # The path as well as the name. A bare name lands in the projects
    # directory rather than wherever this server was started from, so
    # where it actually went is something the window has to be told
    # rather than something it can work out from what was typed.
    return JSONResponse({"ok": True, "name": project.name, "path": str(project.path)})


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
    instructions: str | None = None


@app.patch("/api/projects")
def edit_project(body: EditProject) -> dict:
    if body.label is not None:
        workspace.rename(body.path, body.label)
    if body.pinned is not None:
        workspace.pin(body.path, body.pinned)
    if body.instructions is not None:
        workspace.instruct(body.path, body.instructions)
    return {"ok": True}


class StartJob(BaseModel):
    project: str
    command: str
    # A cap in dollars, for the engine that spends dollars. On a Claude plan
    # nothing is billed per run, so a cap there is a limit this application
    # invented and then enforced against work somebody had already paid for -
    # which is how a four-item website stopped after three.
    budget: float = 4.0
    engine: str = "claude"

    @field_validator("engine")
    @classmethod
    def _only_the_subscription(cls, said: str) -> str:
        """Nothing but the subscription, said at the edge.

        The window cannot ask for anything else and neither can anybody
        posting to this by hand. Refused here rather than accepted and
        then refused deep inside a worker, where the run has already
        started and the person is watching a spinner.
        """
        if (said or "claude").strip() != "claude":
            raise ValueError(
                "this crew runs on a Claude subscription; the API engine "
                "was removed because it bills on top of a paid plan"
            )
        return "claude"

    model: str = "opus"
    # How much ceremony this job gets: fast, balanced or deep. Empty means
    # whatever this person has set, which starts as balanced.
    profile: str = ""
    # How long this run may take, in minutes. Zero, the default, is no
    # deadline. When it is set the run ends at that point whatever it is
    # doing: the workers are stopped and nothing else is started, rather
    # than the request being noted and acted on whenever the current item
    # happens to finish.
    minutes: float = 0.0


class Reading(BaseModel):
    project: str
    text: str


@app.post("/api/read")
def read_intent(body: Reading) -> dict:
    """What a sentence is asking for, without spending anything to find out.

    Deterministic, so the answer comes back in a millisecond and costs
    nothing. It is shown before anything runs and can be overruled, because
    a router that quietly chooses wrong is worse than no router at all.
    """
    guess = intent.read(body.text, Path(body.project) if body.project else None)
    command = next((c for c in available(SKILLS) if c.name == guess.command), None)
    return {
        "command": guess.command,
        "why": guess.why,
        "sure": guess.sure,
        "summary": command.summary if command else "",
        "ceremony": command.ceremony if command else True,
    }


@app.post("/api/start")
def start(body: StartJob) -> JSONResponse:
    commands = available(SKILLS)
    # A sentence with no command on the front of it is read rather than
    # refused. Typing /fix before something that plainly is a fix is a tax
    # on using this.
    said = body.command.strip()
    if not said.startswith("/"):
        guess = intent.read(said, Path(body.project))
        said = f"{guess.command} {said}"

    command, rest = match(said, commands)
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

    busy = workspace.busy_with(Path(body.project))
    if busy:
        return JSONResponse(
            {
                "ok": False,
                "reason": (
                    "a crew is already working in that repository. Stop it "
                    "first - starting another now would put two of them in "
                    "the same tree."
                ),
                "key": busy,
            },
            status_code=409,
        )

    skills = [load_skill(command.skill)] if command.skill else []
    standing = next(
        (p.instructions for p in workspace.projects if str(p.path) == body.project),
        "",
    )
    session = workspace.start(
        Path(body.project),
        command.task_for(rest),
        skills,
        0.0 if body.engine == "claude" else body.budget,
        body.engine,
        body.model,
        command.stop_after,
        standing,
        body.profile,
        body.minutes,
    )
    key = next(k for k, v in workspace.sessions.items() if v is session)
    return JSONResponse({"ok": True, "key": key})


class Preview(BaseModel):
    project: str


@app.post("/api/preview")
def open_preview(body: Preview) -> JSONResponse:
    """Start the project and hand back a URL.

    A job ends with commits and a green suite, and then the only question
    anybody has is where to look at the thing. Answering it with a paragraph
    about which command to type is answering a different question.
    """
    repo = Path(body.project)
    try:
        running = preview.running(repo)
        live = running or preview.start(repo)
    except LookupError as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    except (RuntimeError, TimeoutError) as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
    # Whether the port answers and whether the project has a page there are
    # two different questions, and the window had one green dot for both.
    # Asked here rather than in the browser: the frame is cross-origin, so
    # the page cannot read the status of what it just loaded.
    served = preview.what_it_serves(live.url)
    return JSONResponse(
        {
            "ok": True,
            "url": live.url,
            "command": live.command,
            "already": bool(running),
            "status": served.status,
            "content_type": served.content_type,
            "is_a_page": served.is_a_page,
            "served": served.said,
        }
    )


@app.delete("/api/preview")
def close_preview(body: Preview) -> dict:
    return {"ok": True, "stopped": preview.stop(Path(body.project))}


class Publishing(BaseModel):
    run: str
    draft: bool = True


@app.post("/api/publish")
def publish_run(body: Publishing) -> JSONResponse:
    """Push the branch and open a pull request carrying the evidence."""
    try:
        run = Run.load(body.run)
    except (OSError, ValueError):
        return JSONResponse({"ok": False, "reason": "no such run"}, status_code=404)

    landed = [r for r in run.results if r.outcome.value == "done"]
    if not landed:
        return JSONResponse(
            {"ok": False, "reason": "nothing landed, so there is nothing to open"},
            status_code=400,
        )

    ready, who = publish.signed_in()
    if not ready:
        return JSONResponse({"ok": False, "reason": who}, status_code=400)

    repo = Path(run.repo)
    live = preview.running(repo)
    ok, said = publish.open_pull_request(
        repo,
        run,
        publish.evidence_from(run, Path("runs") / f"{run.id}.log"),
        url=live.url if live else "",
        draft=body.draft,
    )
    if not ok:
        return JSONResponse({"ok": False, "reason": said}, status_code=400)
    return JSONResponse({"ok": True, "url": said, "author": who})


@app.get("/api/can-publish/{run_id}")
def can_publish(run_id: str) -> dict:
    """Whether a pull request is possible here, and why not if it is not."""
    try:
        run = Run.load(run_id)
    except (OSError, ValueError):
        return {"ok": False, "reason": "no such run"}
    ready, who = publish.signed_in()
    if not ready:
        return {"ok": False, "reason": who}
    if not publish.has_remote(Path(run.repo)):
        return {"ok": False, "reason": "this repository has no remote to push to"}
    return {"ok": True, "author": who}


@app.get("/api/running")
def running_jobs() -> dict:
    """Jobs this server is working on right now.

    The work has always run server-side, so closing or reloading the page
    never stopped it - but the page had no way to find it again afterwards,
    which from the outside is the same thing as having stopped it.
    """
    live = []
    for key, session in workspace.sessions.items():
        if not session.running and not (session.run and session.feed.finished is False):
            continue
        if not session.running:
            continue
        live.append(
            {
                "key": key,
                "repo": str(session.repo),
                "task": session.task.split("\n")[0],
                "awaiting_approval": bool(
                    session.run and session.run.plan and not session.stopping
                ),
            }
        )
    return {"jobs": live}


@app.get("/api/run/{run_id}")
def one_run(run_id: str) -> dict:
    """A finished run, in enough detail to read it back.

    Conversations belong to the project they happened in, and someone coming
    back two days later wants the one about this repository - not a global
    list of everything that has ever run.
    """
    try:
        run = Run.load(run_id)
    except (OSError, ValueError):
        return {"ok": False, "reason": "no such run"}

    return {
        "ok": True,
        "id": run.id,
        "task": run.task,
        "repo": Path(run.repo).name,
        "started": run.started[:16].replace("T", " "),
        "engine": run.engine,
        "model": run.model,
        "cost": round(run.cost, 2),
        "skills": run.skills,
        "baseline": run.baseline.model_dump() if run.baseline else None,
        "findings": run.inventory.findings if run.inventory else [],
        "risks": run.inventory.risks if run.inventory else [],
        "summary": run.plan.summary if run.plan else "",
        "answer": run.answer,
        "items": [
            {
                "id": i.id,
                "title": i.title,
                "plain": i.plain,
                "rationale": i.rationale,
                "verify_with": i.verify_with,
            }
            for i in (run.plan.items if run.plan else [])
        ],
        "results": [
            {
                "id": r.item.id,
                "outcome": r.outcome.value,
                "note": r.note,
                "attempts": r.attempts,
                "commit": r.commit,
                # What the suite stood at when this item was accepted, so
                # the board of a finished run shows the count it reached
                # rather than the one it started from.
                "tests_run": r.tests_run,
            }
            for r in run.results
        ],
        # What each station did, read back out of the event log. Without
        # this the office for a finished run showed nine idle desks: the
        # live stream is gone with the process that served it, and reading
        # the thread back never touched the room at all.
        "crew": crew.what_each_did(events_in(Path("runs") / f"{run.id}.log")),
    }


@app.on_event("shutdown")
def _stop_everything() -> None:
    """Nothing this application started outlives it.

    Without this, closing drydock leaves its workers running, holding the
    repository and still writing to it - which looks, from the next run, like
    a repository that dirties itself.
    """
    stopped = stop_workers()
    if stopped:
        print(f"stopped {stopped} worker(s) still running")
    previews = preview.stop()
    if previews:
        print(f"stopped {previews} preview(s)")


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


@app.post("/api/resume/{run_id}")
def resume(run_id: str, minutes: float = 0.0) -> JSONResponse:
    """Carry on a plan that was interrupted."""
    try:
        run = Run.load(run_id)
    except (OSError, ValueError):
        return JSONResponse({"ok": False, "reason": "no such run"}, status_code=404)
    if run.plan is None:
        return JSONResponse(
            {"ok": False, "reason": "that run never got as far as a plan"},
            status_code=400,
        )
    landed = {r.item.id for r in run.results if r.outcome.value == "done"}
    left = [i for i in run.plan.items if i.id not in landed]
    if not left:
        return JSONResponse(
            {"ok": False, "reason": "every item in that plan already has a result"},
            status_code=400,
        )

    # Resuming a run that is still going starts a second crew on the same
    # repository. Both work the same item, both commit into the same tree,
    # and the first one to finish cleans up the other's worker. It is the
    # worst thing this program can do to somebody's code and it was one
    # click away: the only clue in the record was two heartbeats in the
    # same second reporting different amounts of elapsed time.
    key = f"{run.id}-resumed"
    busy = workspace.busy_with(Path(run.repo))
    if busy:
        return JSONResponse(
            {
                "ok": False,
                "reason": (
                    "a crew is already working in that repository. Stop it "
                    "first - starting another now would put two of them in "
                    "the same tree."
                ),
                "key": busy,
            },
            status_code=409,
        )

    try:
        session = Session.resume(
            run, engine=run.engine, model=run.model, within_minutes=minutes
        )
    except GitError as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=409)
    workspace.sessions[key] = session
    return JSONResponse({"ok": True, "key": key, "left": len(left)})


@app.post("/api/stop/{key}")
def stop(key: str, now: bool = False) -> dict:
    """Ask a run to stop, or end it.

    Asked, by default: nothing new starts and the worker in flight
    finishes into a clean tree. That is the kind thing to do and it was
    the only thing on offer, which made the button a lie - an engineer
    has twelve minutes for an attempt, so "stop" could mean twelve
    minutes of watching nothing stop, with the button already disabled
    and no way to say it again.

    Told, with `now`: the workers are ended, which is what the deadline
    already does. The item in flight is thrown away unfinished, by the
    same path a refused item takes.
    """
    session = workspace.session_for(key)
    if session is None:
        return {"ok": False, "reason": "no such run"}
    session.stop(now=now)
    return {"ok": True, "now": now}


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
    # A plan can arrive after somebody asked the run to stop: the worker
    # writing it does not stop mid-sentence. Approving one then starts
    # work on a run whose worktrees are being taken away underneath it,
    # which came back as `IndexError: list index out of range`.
    if session.stopping:
        return {
            "ok": False,
            "reason": "this run was stopped. Its plan is still here - start "
            "it again and it will be approved from the beginning.",
        }
    session.approve()
    return {"ok": True}
