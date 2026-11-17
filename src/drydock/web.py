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


def _page(body: str, script: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>drydock</title><link rel='stylesheet' href='/static/app.css'></head>"
        f"<body><div class='wrap'>{body}</div>"
        f"<script src='/static/{script}'></script></body></html>"
    )


HOME = """
  <header><h1>drydock</h1><span class="task">a crew that changes code and proves it still works</span></header>
  <p class="meta" id="meta"></p>

  <h2>Project</h2>
  <div class="projects" id="projects"></div>
  <div class="bar">
    <input id="newpath" placeholder="path to a git repository" spellcheck="false">
    <button class="ghost" id="addproject">Add</button>
  </div>

  <h2>What should the crew do</h2>
  <div class="cmdbar">
    <input id="command" placeholder="type / to see what it can do" spellcheck="false" autocomplete="off">
    <button id="go" disabled>Start</button>
  </div>
  <div class="suggest" id="suggest"></div>
  <p class="hint" id="hint"></p>

  <h2>Earlier runs</h2>
  <div class="runs" id="runs"></div>
"""

RUN = """
  <header><h1>drydock</h1><span class="task" id="task">starting</span></header>
  <p class="meta" id="meta"><a href="/">&larr; all projects</a></p>
  <div class="board" id="desks"></div>
  <div class="scores" id="scores"></div>
  <div class="bar">
    <button id="approve" disabled>Approve the plan</button>
    <span class="hint" id="hint">surveying the repository</span>
  </div>
  <h2>The plan</h2>
  <p class="summary" id="summary"></p>
  <div class="items" id="items"></div>
  <h2>What the crew is doing</h2>
  <div class="feed" id="feed"></div>
"""


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return _page(HOME, "home.js")


@app.get("/run/{key}", response_class=HTMLResponse)
def run_page(key: str) -> HTMLResponse:
    return _page(RUN, "run.js")


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
        Path(body.project), command.task_for(rest), skills, body.budget
    )
    key = next(k for k, v in workspace.sessions.items() if v is session)
    return JSONResponse({"ok": True, "key": key})


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
