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


# A port the project named for itself. We ask for one through PORT and most
# servers honour it, but a script that hardcodes its own is both common and
# invisible to us: `python3 -m http.server 4321` served that page perfectly
# for twenty-five seconds while this waited on a different number and then
# reported that nothing had answered. Nobody looked at the page as a
# result, which is the cost this is here to stop.
#
# Last resort, and only while the process we started is still alive, so an
# unrelated server on a number we guessed is not mistaken for the project.
# Each alternative is a place a port is named on purpose, so a version
# number or a timeout cannot be read as one. The `:-NNNN` form is the shell
# default in `"${PORT:-4321}"`: it only applies when PORT is unset, and a
# project that writes it is telling us which number it falls back to.
NAMED = re.compile(
    r"--port[=\s]+(\d{2,5})"
    r"|-p[=\s]+(\d{2,5})"
    r"|http\.server\s+\D{0,12}?(\d{2,5})"
    r"|:-\s*(\d{2,5})"
    r"|\bserve\s+(\d{2,5})"
)


def _ports_named_in(command: str, repo: Path | None = None) -> list[int]:
    """Ports named by the command, and by the script it stands for.

    `npm run start` names nothing; the number is in package.json, which is
    where the project actually hardcoded it. Scanning only what we type
    would have missed the whole of the case this exists for.
    """
    text = command
    said = re.match(r"npm run ([\w:-]+)$", command.strip())
    if said and repo is not None:
        try:
            scripts = json.loads((repo / "package.json").read_text()).get("scripts")
            text += " " + str((scripts or {}).get(said.group(1), ""))
        except (OSError, ValueError, AttributeError):
            pass
    found = [int(p) for hit in NAMED.findall(text) for p in hit if p]
    return [p for p in found if 1 <= p <= 65535]


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


# Links a page makes to its own site, in the order it makes them. A page
# is the only thing that knows what the rest of the site is: a project may
# be four files or four hundred, built by anything, and the nav at the top
# of its home page names the pages a person is meant to reach. Nothing
# here guesses from the directory layout, which is a different question
# with a different answer for every framework.
# Only `<a>`. The first attempt matched any `href` and came back with the
# favicon and the stylesheet, which are things the page loads rather than
# pages a person goes to.
_LINK = re.compile(r"""<a\s[^>]*?href\s*=\s*["'](/[^"'#?>]*)""", re.IGNORECASE)

# And nothing that is plainly a file. A link straight to a PDF or an image
# is a real link and it is not a page of the site.
_A_FILE = re.compile(
    r"\.(?:css|js|mjs|json|xml|txt|pdf|zip|png|jpe?g|gif|svg|webp|avif|ico|"
    r"woff2?|ttf|otf|mp4|webm|mp3|wav)$",
    re.IGNORECASE,
)


def routes_on(url: str, cap: int = 2, timeout: float = 3.0) -> list[str]:
    """Up to `cap` other pages this one links to, deduplicated, in order.

    The home page itself is never one of them - it is the page that was
    read - and anything that is not a plain route is dropped rather than
    cleaned up. Empty on anything that goes wrong: this widens a look
    when it can and is never a reason for one not to happen.
    """
    import urllib.error
    import urllib.request

    from .route import is_route

    try:
        with urllib.request.urlopen(url, timeout=timeout) as answer:
            if "html" not in answer.headers.get("Content-Type", "").lower():
                return []
            page = answer.read(400_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []

    found: list[str] = []
    for href in _LINK.findall(page):
        said = href if href.startswith("/") else "/" + href
        # One page per route, however the page spells it. `/rooms` and
        # `/rooms/` are the same door.
        if (
            said != "/"
            and is_route(said)
            and not _A_FILE.search(said)
            and said.rstrip("/") not in [s.rstrip("/") for s in found]
        ):
            found.append(said)
        if len(found) >= cap:
            break
    return found


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
    # PYTHONUNBUFFERED because `_announced` reads the log while the server
    # is still running, and a Python server's "Serving HTTP on ..." line
    # sits in a block buffer until the process ends - which is never, for a
    # server that works. The one line we most need to read was the one we
    # could not.
    env = {"PORT": str(port), "HOST": "127.0.0.1", "PYTHONUNBUFFERED": "1"}

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
        mine = _ports_named_in(command, repo) if process.poll() is None else []
        for candidate in [p for p in (said, port, *mine) if p]:
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


def _still_that_command(pid: int, command: str) -> bool:
    """Whether this pid is still running what we wrote down for it.

    A pid is reused. Confirming the port answers says something is
    serving; this says the something is the thing we started, so a
    number that has come round again on an unrelated process is not
    signalled. Both have to hold.
    """
    if not pid or not command.strip():
        return False
    try:
        said = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    said = said.strip()
    if not said:
        return False
    # The first real word of the recorded command - `npm`, `node`,
    # `python3` - has to appear in what is running now. Loose on purpose:
    # a shell wrapper changes the rest of the line and not this.
    first = next((w for w in shlex.split(command) if not w.startswith("-")), "")
    return bool(first) and Path(first).name in said


def reap() -> int:
    """Stop every preview written down by an application that has gone.

    `stop()` works on `_RUNNING`, which is in memory. A fresh process
    owns no previews, so it reaps none of the ones it finds, and a dev
    server outlives the application that started it - keeping its port.

    Measured, on this machine, after a week of runs: two `http.server`
    processes three days old and a `node server.js` holding 4173. An
    engineer then could not start its own preview, and said so itself -
    "two of the three looks were spent on those failed starts". The
    looks are the only way it sees the page it is building.

    Called once when the application starts. A preview this process
    starts is its own and is stopped the ordinary way.

    Two things have to hold before anything is signalled: the recorded
    port still answers, and the recorded pid is still running the
    recorded command. Either alone could point at somebody else's
    process.
    """
    stopped = 0
    for note in sorted(_roster().glob("*.json")):
        try:
            said = json.loads(note.read_text())
            port = int(said["url"].rsplit(":", 1)[1])
        except (OSError, ValueError, KeyError, IndexError):
            note.unlink(missing_ok=True)
            continue
        note.unlink(missing_ok=True)
        pid = int(said.get("pid") or 0)
        if not _answers(port) or not _still_that_command(pid, said.get("command", "")):
            continue
        _signal_group(_Elsewhere(pid), signal.SIGTERM)
        stopped += 1
    return stopped


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
            # The whole group, not the one process. These are started with
            # `shell=True`, so the pid belongs to the shell, and whether
            # that shell execs the real server or forks it is a difference
            # between one machine's /bin/sh and another's. Signalling only
            # the pid left a static server answering on a port after it had
            # been stopped - on Linux, not here, which is the worst way to
            # find out. `start_new_session=True` exists for exactly this:
            # every preview is its own group leader.
            _signal_group(preview.process, signal.SIGTERM)
            try:
                preview.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _signal_group(preview.process, signal.SIGKILL)
            stopped += 1
    return stopped


def _signal_group(process, sign: int) -> None:
    """Signal a preview's whole process group, or it alone if it has none."""
    pid = getattr(process, "pid", 0)
    if pid:
        try:
            os.killpg(os.getpgid(pid), sign)
            return
        except (OSError, AttributeError):
            # No group, or gone already. Fall through to the one process.
            pass
    with contextlib.suppress(OSError):
        process.kill() if sign == signal.SIGKILL else process.terminate()
