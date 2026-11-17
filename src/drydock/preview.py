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


_RUNNING: dict[str, Preview] = {}
_LOCK = threading.Lock()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _answers(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        try:
            sock.connect(("127.0.0.1", port))
            return True
        except OSError:
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
    log = repo / ".drydock-preview.log"
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
        if process.poll() is not None:
            raise RuntimeError(
                f"`{command}` exited straight away.\n\n"
                + log.read_text()[-900:].strip()
            )
        if _answers(port):
            preview = Preview(
                project=str(repo),
                url=f"http://127.0.0.1:{port}",
                command=command,
                process=process,
                log=log,
            )
            with _LOCK:
                _RUNNING[str(repo)] = preview
            return preview
        time.sleep(0.25)

    process.terminate()
    raise TimeoutError(
        f"`{command}` ran for {timeout:.0f} seconds without answering on a port.\n\n"
        + log.read_text()[-900:].strip()
    )


def running(repo: Path) -> Preview | None:
    with _LOCK:
        preview = _RUNNING.get(str(repo))
    if preview and preview.process.poll() is None:
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
        if preview.process.poll() is None:
            preview.process.terminate()
            try:
                preview.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                preview.process.kill()
            stopped += 1
    return stopped
