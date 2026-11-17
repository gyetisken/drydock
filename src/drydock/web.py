"""The live view.

One run, one page. The server holds the session and streams what it does; the
page draws it. There is no state in the browser that did not arrive as an
event, so a reload shows the same thing and nothing can be displayed that the
run did not actually report.
"""

import queue
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .session import Session

app = FastAPI(title="drydock")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

session: Session | None = None

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>drydock</title><link rel="stylesheet" href="/static/app.css"></head>
<body><div class="wrap">
  <header><h1>drydock</h1><span class="task" id="task">starting</span></header>
  <p class="meta" id="meta"></p>

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
</div><script src="/static/app.js"></script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(PAGE)


@app.get("/favicon.ico")
def favicon():
    return FileResponse(STATIC / "app.css", media_type="image/x-icon")


@app.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    if session is None:
        raise RuntimeError("no session")
    listener = session.feed.listen()

    async def pump():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = listener.get(timeout=1.0)
                except queue.Empty:
                    # A comment keeps the connection alive through proxies and
                    # lets the disconnect check above run on a fixed cadence.
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


@app.post("/approve")
def approve() -> dict:
    if session is None or session.run is None or session.run.plan is None:
        return {"ok": False, "reason": "there is no plan to approve yet"}
    session.approve()
    return {"ok": True}
