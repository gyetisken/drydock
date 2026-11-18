"""Running the thing that was just built.

A job ends with four commits and a green suite, and then somebody asks the
only question that matters: where do I look at it. Answering that with a
paragraph about `npm start` is answering a different question.

So this starts the project the way its own manifest says it should be
started, on a port nobody is using, waits until it actually answers, and
hands back a URL. It is deliberately small: one process at a time per
project, stopped when asked or when the application exits, and nothing is
guessed - if the project does not say how to run itself, this says so rather
than inventing a command.

The one exception is a folder with an `index.html` in it and no manifest.
That is not a project keeping quiet about how it runs; it is a project
saying it is a page, and a static server is not a guess about it - it is
the only thing it could mean. Without this a plain HTML site could not be
previewed at all, and the critic, which is handed a URL or nothing, never
got to look at the one kind of work it exists for.
"""

import contextlib
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Preview:
    project: str
    url: str
    command: str
    process: subprocess.Popen
    log: Path
    # Whether this process is the one serving. A dev server that hands off to
    # a daemon it already started is serving the right thing, and stopping
    # our handle would stop nothing.
    ours: bool = True


_RUNNING: dict[str, Preview] = {}
_LOCK = threading.Lock()


def _roster() -> Path:
    """Where running previews are written down, outside any one process.

    A dict in memory is lost when the application restarts and a dev server
    is not: it keeps the port, keeps watching the files, and keeps serving
    whatever it last built. The next run then either fails to take the port
    or starts a second server beside the first, and somebody looks at a page
    that was built an hour ago and reports that their change did nothing.
    """
    home = Path(os.environ.get("DRYDOCK_HOME") or Path.home() / ".drydock")
    where = home / "previews"
    where.mkdir(parents=True, exist_ok=True)
    return where


def _note_name(repo: Path | str) -> str:
    """One file per project, named so it can be found again."""
    return str(repo).strip("/").replace("/", "-") + ".json"


def _write_down(preview: Preview) -> None:
    try:
        (_roster() / _note_name(preview.project)).write_text(
            json.dumps(
                {
                    "project": preview.project,
                    "url": preview.url,
                    "command": preview.command,
                    "pid": preview.process.pid,
                }
            )
        )
    except OSError:
        pass  # the roster is a convenience, never a precondition


def _strike_off(project: str) -> None:
    try:
        (_roster() / _note_name(project)).unlink(missing_ok=True)
    except OSError:
        pass


def _written_down(repo: Path) -> Preview | None:
    """A preview started before this application was, if it is still up."""
    note = _roster() / _note_name(repo)
    try:
        said = json.loads(note.read_text())
        port = int(said["url"].rsplit(":", 1)[1])
    except (OSError, ValueError, KeyError, IndexError):
        note.unlink(missing_ok=True)
        return None
    if not _answers(port):
        note.unlink(missing_ok=True)
        return None
    return Preview(
        project=said["project"],
        url=said["url"],
        command=said.get("command", ""),
        # Not ours to hold: it belongs to an application that has gone. The
        # pid is kept so it can still be stopped.
        process=_Elsewhere(int(said.get("pid") or 0)),
        log=Path(said.get("log", "")),
        ours=True,
    )


class _Elsewhere:
    """A process this application did not start but can still signal."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        if not self.pid:
            return 0
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return 0
        except PermissionError:
            return None
        return None

    def terminate(self) -> None:
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, signal.SIGTERM)

    def kill(self) -> None:
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        waited = 0.0
        while self.poll() is None and (timeout is None or waited < timeout):
            time.sleep(0.1)
            waited += 0.1
        if self.poll() is None:
            raise subprocess.TimeoutExpired(cmd="preview", timeout=timeout or 0)
        return 0


def _log_for(repo: Path) -> Path:
    """Where this project's preview output goes. Outside the project."""
    import hashlib

    home = Path.home() / ".drydock" / "previews"
    home.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:12]
    return home / f"{repo.name}-{key}.log"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# Nearly every dev server prints the address it is actually serving on, and
# several of them choose that address themselves. Astro in particular runs a
# daemon, ignores PORT, and a second invocation exits immediately saying the
# first one is already up - with the URL in the message. Insisting on a port
# we picked means never finding any of them.
ANNOUNCED = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]):(\d{2,5})")


def _announced(log: Path) -> int | None:
    try:
        found = ANNOUNCED.findall(log.read_text())
    except OSError:
        return None
    return int(found[-1]) if found else None


@dataclass(frozen=True)
class Served:
    """What came back from asking the running project for a page.

    The port answering and the page being there are two different facts,
    and the window had one green dot for both. A service with a /health
    endpoint and no root is working exactly as asked; rendering its 404
    beside "1 of 1 items landed" says the opposite.

    This is done here rather than in the browser because the frame is
    cross-origin - a different port is a different origin - so the page
    cannot read the status of what it just loaded. It can only show
    whatever the server painted.
    """

    status: int = 0
    content_type: str = ""
    error: str = ""

    @property
    def is_a_page(self) -> bool:
        """Whether this is something worth putting in a frame."""
        return 200 <= self.status < 300 and "html" in self.content_type.lower()

    @property
    def said(self) -> str:
        if self.error:
            return self.error
        kind = self.content_type.split(";")[0].strip() or "no content type"
        return f"HTTP {self.status}, {kind}"


def what_it_serves(url: str, path: str = "/", timeout: float = 3.0) -> Served:
    """Ask the running project for one page and report what came back.

    One request, short timeout, nothing followed and nothing retried. It
    reports what it observed - including a 404, which is a fact about the
    project and not a failure of this program.
    """
    import urllib.error
    import urllib.request

    target = url.rstrip("/") + "/" + path.lstrip("/")
    try:
        with urllib.request.urlopen(target, timeout=timeout) as answer:
            return Served(
                status=answer.status,
                content_type=answer.headers.get("Content-Type", ""),
            )
    except urllib.error.HTTPError as refused:
        # A status this program did not want is still a status, and the
        # honest thing is to report it rather than to call it an error.
        return Served(
            status=refused.code,
            content_type=refused.headers.get("Content-Type", ""),
        )
    except urllib.error.URLError as exc:
        return Served(error=f"it did not answer: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        return Served(error=f"it did not answer: {exc}")


def _answers(port: int) -> bool:
    """Whether anything is listening, on either address family.

    This used to try IPv4 only, and a dev server bound to [::1] - which is
    what Node does by default when given `localhost` - was invisible to it.
    The server was up, the page loaded in a browser, and drydock reported
    that it had never started.
    """
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.4)
                sock.connect((host, port))
                return True
        except OSError:
            continue
    return False


def how_to_run(repo: Path) -> tuple[str, str]:
    """The command this project says starts it, and why that one.

    Only what the project states about itself. A guess that happens to work
    once is worse than nothing, because the next person inherits it.
    """
    manifest = repo / "package.json"
    if manifest.exists():
        try:
            scripts = json.loads(manifest.read_text()).get("scripts") or {}
        except (OSError, ValueError):
            scripts = {}
        for name in ("start", "dev", "serve"):
            if name in scripts:
                return f"npm run {name}", f"package.json defines a {name} script"

    for name, command in (
        ("manage.py", "python manage.py runserver"),
        ("app.py", "python app.py"),
        ("main.py", "python main.py"),
    ):
        if (repo / name).exists():
            return command, f"{name} is in the project root"

    # Last, so anything that states a server of its own wins. A page and a
    # server in the same folder means the server renders the page.
    if (repo / "index.html").exists():
        # This interpreter, not whatever `python3` resolves to on the path:
        # the machine running drydock has one for certain, and a system
        # python that is missing or is 2.7 would fail here for a reason
        # that has nothing to do with the project.
        serve = f'{shlex.quote(sys.executable)} -m http.server "$PORT" --bind 127.0.0.1'
        why = "index.html is in the project root and nothing else says how to start it"
        return serve, why

    return "", "this project does not say how to start itself"


def start(repo: Path, timeout: float = 25.0) -> Preview:
    """Start the project and wait until the port answers."""
    stop(repo)

    command, why = how_to_run(repo)
    if not command:
        raise LookupError(why)

    port = _free_port()
    # Not in the repository. drydock refuses to let the crew leave files in
    # somebody's project and then left its own there, where it dirtied the
    # tree and stopped the next job before it started.
    log = _log_for(repo)
    env = {"PORT": str(port), "HOST": "127.0.0.1"}

    with log.open("w") as out:
        # The command came from the project's own manifest, not from us.
        process = subprocess.Popen(
            command,
            cwd=repo,
            shell=True,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**os.environ, **env},
            start_new_session=True,
        )

    deadline = time.time() + timeout
    while time.time() < deadline:
        said = _announced(log)
        # The port it says it is on, then the one we asked for. A server that
        # exited may still have announced a useful address on its way out -
        # Astro's second invocation reports where the first one is listening.
        for candidate in [p for p in (said, port) if p]:
            if _answers(candidate):
                preview = Preview(
                    project=str(repo),
                    url=f"http://localhost:{candidate}",
                    command=command,
                    process=process,
                    log=log,
                    ours=process.poll() is None,
                )
                with _LOCK:
                    _RUNNING[str(repo)] = preview
                _write_down(preview)
                return preview

        # A command that hands off to a daemon exits before the daemon is
        # listening. Having been told an address, keep knocking on it rather
        # than giving up because the process we started has gone.
        if process.poll() is not None and said is None:
            raise RuntimeError(
                f"`{command}` stopped without serving anything.\n\n"
                + log.read_text()[-900:].strip()
            )
        time.sleep(0.25)

    process.terminate()
    raise TimeoutError(
        f"`{command}` ran for {timeout:.0f} seconds without answering on a port.\n\n"
        + log.read_text()[-900:].strip()
    )


def running(repo: Path) -> Preview | None:
    with _LOCK:
        preview = _RUNNING.get(str(repo))
    # Still good if the port answers, whether or not our own handle is alive.
    if preview and _answers(int(preview.url.rsplit(":", 1)[1])):
        return preview
    if preview:
        with _LOCK:
            _RUNNING.pop(str(repo), None)
        _strike_off(str(repo))

    # Nothing in memory. There may still be one from before this application
    # started - a dev server does not stop because the thing that started it
    # did.
    left_over = _written_down(repo)
    if left_over:
        with _LOCK:
            _RUNNING[str(repo)] = left_over
    return left_over


def stop(repo: Path | None = None) -> int:
    """Stop one preview, or all of them."""
    with _LOCK:
        targets = (
            [_RUNNING.pop(str(repo))]
            if repo and str(repo) in _RUNNING
            else list(_RUNNING.values())
        )
        if repo is None:
            _RUNNING.clear()
    if repo is not None and not targets:
        left_over = _written_down(repo)
        targets = [left_over] if left_over else []
    stopped = 0
    for preview in targets:
        _strike_off(preview.project)
        if preview.ours and preview.process.poll() is None:
            preview.process.terminate()
            try:
                preview.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                preview.process.kill()
            stopped += 1
    return stopped
