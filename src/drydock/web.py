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
    <div class="brand"><b>drydock</b><i>changes code, proves it still works</i></div>

    <div class="side-h">Projects <button id="plus" title="add a repository">+</button></div>
    <div class="addbox" id="addbox">
      <input id="newpath" placeholder="/path/to/a/git/repository" spellcheck="false">
      <div class="row">
        <button class="btn small" id="add">Add</button>
        <button class="btn small ghost" id="cancel">Cancel</button>
      </div>
    </div>
    <div class="side-list" id="projects"></div>

    <div class="side-h">Earlier</div>
    <div class="side-list grow" id="history"></div>
  </aside>

  <main>
    <div class="topbar">
      <b id="proj">no project</b><span class="sub" id="chain"></span>
      <div class="right">
        <span id="spend"></span>
        <button class="btn small ghost" id="stop" style="display:none">Stop</button>
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

    <div class="composer"><div class="cwrap">
      <div class="menu" id="menu" style="display:none"></div>
      <div class="cbox">
        <textarea id="box" rows="1" placeholder="/ to see commands" spellcheck="false"></textarea>
        <select id="engine" title="whose account does the work"></select>
      </div>
      <div class="hint" id="hint"></div>
    </div></div>
  </main>

</div><script src="/static/chat.js"></script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(PAGE)


def _engines() -> list[dict]:
    """Which ways of running the crew are actually available here."""
    import os
    import shutil

    return [
        {
            "id": "claude",
            "label": "Your Claude account",
            "detail": "runs through Claude Code, signed in as you",
            "ready": bool(shutil.which("claude")),
            "why": "Claude Code is not installed on this machine",
        },
        {
            "id": "api",
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
                "toolchain": p.toolchain(),
                "last_used": p.last_used,
                "ok": p.exists,
            }
            for p in workspace.projects
        ],
        "engines": _engines(),
        "commands": [
            {
                "name": c.name,
                "summary": c.summary,
                "asks": c.asks,
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
    workspace.forget(body.path)
    return {"ok": True}


class StartJob(BaseModel):
    project: str
    command: str
    budget: float = 4.0
    engine: str = "claude"


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
    )
    key = next(k for k, v in workspace.sessions.items() if v is session)
    return JSONResponse({"ok": True, "key": key})


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
