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
"""

import json
import os
import re
import socket
import subprocess
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
    return None


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
    stopped = 0
    for preview in targets:
        if preview.ours and preview.process.poll() is None:
            preview.process.terminate()
            try:
                preview.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                preview.process.kill()
            stopped += 1
    return stopped
