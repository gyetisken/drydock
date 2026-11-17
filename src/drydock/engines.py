"""Where the model comes from.

Two ways to run the same crew, and the difference is whose account pays.

The API engine talks to the Anthropic API with a key, which bills per token and
gives precise control: our own tool definitions, strict schemas, a hard budget
that stops a run mid-flight.

The Claude Code engine shells out to the `claude` command already installed and
signed in on the machine, so the work runs on whatever plan that person has.
Control is coarser — the tools are Claude Code's, not ours — and in exchange
nobody has to paste an API key into this application, and nothing it does costs
money per run.

What does not change between them is everything that makes this trustworthy:
the baseline, one commit per item, the verification, and the rollback. Those
are ours either way, which is the point. The engine writes code; the harness
decides whether the code is allowed to stay.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


class EngineUnavailable(RuntimeError):
    pass


@dataclass
class EngineResult:
    done: bool
    summary: str
    files_changed: list[str]
    noticed: list[str]
    # Something the engineer could not settle on its own. Empty almost
    # always; when it is not, nothing was changed and the item is waiting
    # on an answer rather than on another attempt.
    question: str = ""
    # The worker was taken away rather than finishing. Not the same thing as
    # an item the engineer could not do, and it calls for the opposite
    # response: try the same item again rather than giving up on it.
    died: bool = False
    dollars: float = 0.0
    turns: int = 0


# What may be run when the project does not have a build command yet. A
# greenfield item has to be able to create one, and a repository with no
# toolchain cannot name the tool it is about to install. This is the list of
# things that bring a project into existence - not a shell. Nothing here
# fetches from the network except a package manager doing its job, and
# nothing here deletes.
BOOTSTRAP = (
    "npm",
    "npx",
    "pnpm",
    "yarn",
    "node",
    "python",
    "python3",
    "uv",
    "pip",
    "pip3",
    "go",
    "cargo",
    "mvn",
    "gradle",
    "dotnet",
    "mkdir",
    "ls",
    "cat",
)


def _shell_rule(build_command: str) -> str:
    """Which shell commands the worker may run.

    Once a project has a build command the worker is held to it, which is as
    narrow as this gets. Before then it would be held to nothing, and the
    earlier version of this line simply crashed on the empty string - which
    is how greenfield jobs died the moment they reached the first item.
    """
    tool = build_command.split()[0] if build_command.strip() else ""
    if tool:
        return f"Bash({tool} *)"
    return " ".join(f"Bash({name} *)" for name in BOOTSTRAP)


# Every worker currently running, so they can be stopped.
#
# subprocess.Popen does not tie a child to its parent: killing this
# application leaves the `claude` process alive, still holding the repository
# and still writing files into it. That is how a resumed run found its tree
# dirty seconds after cleaning it - an orphan from the previous run was
# recreating the files behind it. A process nobody can stop is not a worker,
# it is a leak with a shell.
# How often a quiet worker is looked in on, and how long it has to have
# been quiet before that is worth saying. Named rather than written into
# the loop so a test can wind them down instead of sitting through them.
QUIET_EVERY = 30
QUIET_AFTER = 90

# How long a worker may show nothing before it is treated as stopped rather
# than busy. Working looks like a tool call every few seconds, so five
# minutes with nothing to show is not a long turn.
#
# Measured against what a person would have seen, not against the raw
# output. A worker waiting on a connection that has stalled still has lines
# coming down the pipe - keepalives - so by that measure it is talking, and
# one sat at under one percent of a processor for six minutes looking
# perfectly healthy. The only honest signal is that nothing appeared.
SILENT_LIMIT = 300

_WORKERS: set[subprocess.Popen] = set()
_WORKERS_LOCK = threading.Lock()

# Every signal this program sends a worker, by pid. A worker that died of a
# signal nobody here sent is a different problem from one this program
# stopped on purpose, and for two days the two were indistinguishable from
# the outside - an item would simply end with "exited 143" and no account of
# who asked. Writing it down is cheap and turns a mystery into a fact.
_SIGNALLED: dict[int, str] = {}


def _asked_to_stop(process, why: str) -> None:
    """Send a worker a signal, and remember that it was us."""
    pid = getattr(process, "pid", None)
    if pid is not None:
        _SIGNALLED[pid] = why
    try:
        process.terminate()
    except OSError:
        pass


def _roster() -> Path:
    """Where running workers are written down, outside any one process.

    A set in memory is lost when the application restarts, and a worker is
    not: it keeps its turn, keeps writing files, and the next run finds a
    repository with somebody else's hands in it. Two engineers wrote the
    same page at once this way, and one of them said so in its own notes
    while nothing in this program noticed.

    So the roster is on disk. It is a cache of something the operating
    system already knows, which is why nothing here trusts it further than
    a pid and a path.
    """
    home = Path(os.environ.get("DRYDOCK_HOME") or Path.home() / ".drydock")
    where = home / "workers"
    where.mkdir(parents=True, exist_ok=True)
    return where


def _watch(process: subprocess.Popen) -> None:
    with _WORKERS_LOCK:
        _WORKERS.add(process)
    pid = getattr(process, "pid", None)
    try:
        (_roster() / f"{pid}.json").write_text(
            json.dumps({"pid": pid, "repo": getattr(process, "drydock_repo", "")})
        )
    except (OSError, TypeError):
        pass  # the roster is a convenience, never a precondition


def _forget(process: subprocess.Popen) -> None:
    with _WORKERS_LOCK:
        _WORKERS.discard(process)
    try:
        (_roster() / f"{getattr(process, 'pid', None)}.json").unlink(missing_ok=True)
    except OSError:
        pass


def _alive(pid: int) -> bool:
    """Whether this pid is a process that is still doing something.

    A process that has exited but not been reaped still answers signal 0,
    so a stopped worker looked alive forever and was counted as one. The
    state flag is what separates the two.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # somebody else's, but it exists
    try:
        said = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return True
    state = said.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _orphans(repo: Path | None) -> list[int]:
    """Workers written down by a process that is no longer here.

    Anything in the roster that this process does not own is either dead -
    in which case the note is swept - or alive and not being watched by
    anybody, which is the case worth stopping.
    """
    with _WORKERS_LOCK:
        ours = {p.pid for p in _WORKERS}
    found = []
    for note in _roster().glob("*.json"):
        try:
            said = json.loads(note.read_text())
            pid = int(said["pid"])
        except (OSError, ValueError, KeyError):
            note.unlink(missing_ok=True)
            continue
        if not _alive(pid):
            note.unlink(missing_ok=True)
            continue
        if pid in ours:
            continue
        if repo is None or said.get("repo") == str(repo):
            found.append(pid)
    return found


def stop_workers(repo: Path | None = None) -> int:
    """Stop every running worker, or only those working in one repository.

    Asked first, then told. A worker given a moment to exit closes its own
    files; one that is killed outright can leave a half-written report
    behind, which the engine would then read as a finished answer.
    """
    with _WORKERS_LOCK:
        targets = [
            p
            for p in _WORKERS
            if p.poll() is None
            and (repo is None or getattr(p, "drydock_repo", None) == str(repo))
        ]
    for process in targets:
        _asked_to_stop(process, "everything in this repository was stopped")
    for process in targets:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
        _forget(process)

    stopped = len(targets)
    for pid in _orphans(repo):
        for signal_number in (signal.SIGTERM, signal.SIGKILL):
            if not _alive(pid):
                break
            try:
                os.kill(pid, signal_number)
            except OSError:
                break
            time.sleep(0.4)
            # If it happens to be a child of this process, reap it, or it
            # stays on the roster as a process that answers signals and does
            # nothing. Orphans of a previous run are not ours and launchd
            # reaps those.
            try:
                os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass
        if not _alive(pid):
            (_roster() / f"{pid}.json").unlink(missing_ok=True)
            stopped += 1
    return stopped


def _confinement(repo: Path) -> tuple[str, dict]:
    """Settings and environment that keep the worker inside one repository.

    Claude Code has a real filesystem and no reason of its own to stay
    anywhere. Pointed at an empty project it does the sensible thing for an
    assistant and the wrong thing for this: it looks upwards. On one run it
    walked out of an empty folder and surveyed drydock's own source, then
    planned against that - a job about a restaurant website became a job about
    this codebase.

    Permission patterns could not express it: a deny broad enough to cover
    everything outside also covers the repository, and deny wins over allow.
    A PreToolUse hook can, because it sees the actual path.
    """
    settings = json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Read|Edit|Write|Glob|Grep|NotebookEdit",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"{sys.executable} -m drydock.confine",
                            }
                        ],
                    }
                ]
            }
        }
    )
    env = dict(os.environ)
    env["DRYDOCK_ROOT"] = str(repo.resolve())
    # The hook runs as its own process and has to be able to import drydock
    # even when this is running from a checkout rather than an installation.
    here = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = here + os.pathsep + env.get("PYTHONPATH", "")
    return settings, env


class ClaudeCodeEngine:
    """Drive the Claude Code CLI as the worker.

    It already has file tools, a shell, and an account. What it does not have
    is a reason to stop, so the bounds come from here: the directory it may
    touch, the commands it may run, and the number of turns it may take.
    """

    name = "claude"

    def __init__(
        self, model: str = "opus", max_turns: int = 60, minutes: float = 12.0
    ) -> None:
        self.binary = shutil.which("claude")
        if not self.binary:
            raise EngineUnavailable(
                "the `claude` command is not on PATH. Install Claude Code and "
                "sign in, or use the API engine with a key."
            )
        self.model = model
        self.max_turns = max_turns
        # A wall clock as well as a turn count. Turns bound how much a worker
        # does; nothing bounded how long it took, so a worker that stopped
        # producing output stalled the run with no end to it. A run that is
        # over its time is a run that has gone wrong, and saying so beats
        # waiting for an answer that is not coming.
        self.seconds = minutes * 60

    def work(
        self,
        repo: Path,
        system: str,
        prompt: str,
        build_command: str,
        on_event=None,
    ) -> EngineResult:
        report_file = repo / ".drydock-report.json"
        report_file.unlink(missing_ok=True)

        # The turn budget is stated, because a worker that does not know it
        # has one spends the end of it proving work that something else is
        # about to verify anyway, and is cut off before it can report.
        instruction = (
            f"{prompt}\n\n"
            f"You have {self.max_turns} turns. Use roughly the first two "
            "thirds for the item itself and leave the rest; the suite is run "
            "for you afterwards, so turns spent demonstrating that your change "
            "works are turns taken from making it work.\n\n"
            "The last thing you do is write .drydock-report.json in the "
            "repository root, containing exactly this JSON and nothing else:\n"
            '{"done": true, "summary": "...", "files_changed": ["..."], '
            '"noticed": ["..."], "question": ""}\n'
            "Set done to false if the item could not be done as written. Put "
            "anything outside the item's scope into noticed rather than fixing "
            "it. An item that was finished and not reported is thrown away.\n\n"
            "If the item cannot be done because it contradicts itself or the "
            "direction, or because it turns on something nobody has decided, "
            "do not guess and do not do half of it. Put the one thing you "
            "need settled into `question`, as a question with the options you "
            "can see, and change nothing. Whoever wrote the item will answer "
            "and you will be asked again. Use this once and only for a "
            "decision that is not yours to make - not for anything you could "
            "find out by reading the repository."
        )

        command = [
            self.binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--max-turns",
            str(self.max_turns),
            "--permission-mode",
            "acceptEdits",
            # Bounded on purpose: it may read, edit and run the project's own
            # build, and nothing else. Without this it has a shell.
            "--allowedTools",
            "Read Edit Write Glob Grep " + _shell_rule(build_command),
            "--append-system-prompt",
            system,
        ]
        settings, env = _confinement(repo)
        command[1:1] = ["--settings", settings]

        process = subprocess.Popen(
            command,
            cwd=repo,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            # Its own session, so that nothing can take it down by
            # signalling a group. Started as an ordinary child it sits in
            # this application's process group along with every preview
            # server, and anything in there that cleans up after itself by
            # signalling the group - which is what npm does - stops the
            # worker too. A healthy one died twice this way, mid-sentence,
            # with no clock of ours anywhere near it. The preview already
            # ran in its own session; the workers did not.
            start_new_session=True,
        )
        process.drydock_repo = str(repo)
        _watch(process)
        process.stdin.write(instruction)
        process.stdin.close()

        dollars, turns, overran = self._read(process, on_event)
        if overran and on_event:
            on_event("engine", _why_it_stopped(overran, self.seconds))
        _forget(process)

        if not report_file.exists():
            # A worker that fails has to say why. This used to report only
            # that no report appeared, which is the one fact that was already
            # obvious, while the actual reason - a turn limit, a refused
            # permission, a crash - sat unread in a pipe.
            why = (process.stderr.read() or "").strip()[-1200:]
            if overran == "silence":
                # It was this program that killed it, so the exit code is our
                # own signal and says nothing.
                reason = (
                    f"it showed nothing at all for {SILENT_LIMIT // 60} "
                    f"minutes and was stopped. It got through {turns} turns "
                    "first. This is not an item that was too large; it is a "
                    "worker that stopped working, usually on a connection "
                    "that stalled, and the same item is worth trying again"
                )
            elif overran:
                reason = (
                    f"it ran for {self.seconds / 60:.0f} minutes without "
                    f"finishing and was stopped. It got through {turns} turns"
                )
            else:
                reason = "the worker stopped without writing a report"
                if process.returncode:
                    reason += f" and exited {process.returncode}"
                ours = _SIGNALLED.pop(process.pid, "")
                if _was_killed(process.returncode):
                    reason += (
                        f". This program stopped it: {ours}"
                        if ours
                        else ". Nothing in this program asked it to stop, and "
                        "it was in a session of its own where a stray group "
                        "signal cannot reach it - so it gave up on its own. "
                        "That is usually a request that stalled, and it says "
                        "nothing about the item"
                    )
            if not overran and turns >= self.max_turns:
                reason += (
                    f". It used all {self.max_turns} turns it was given, which "
                    "usually means the item is too large to be one item"
                )
            if why:
                reason += f".\n\n{why}"
            return EngineResult(
                done=False,
                summary=reason,
                files_changed=[],
                noticed=[],
                # A worker that stopped showing anything is a worker that
                # stopped working, which is not the item's fault and is
                # worth trying again. A worker that used its whole clock
                # really did use it, and would use it again.
                died=overran == "silence"
                or (_was_killed(process.returncode) and not overran),
                dollars=dollars,
                turns=turns,
            )
        payload = json.loads(report_file.read_text())
        report_file.unlink(missing_ok=True)
        return EngineResult(
            done=bool(payload.get("done")),
            summary=payload.get("summary", ""),
            files_changed=payload.get("files_changed", []),
            noticed=payload.get("noticed", []),
            question=str(payload.get("question") or "").strip(),
            dollars=dollars,
            turns=turns,
        )

    def _read(self, process, on_event) -> tuple[float, int, str]:
        """Drain the worker's output, and stop it if it runs over its time.

        The timer runs on its own thread because reading a pipe blocks: a
        worker that has gone quiet is exactly the case this has to catch, and
        a quiet pipe gives nothing to check a deadline against.
        """
        overran = threading.Event()

        def ran_out() -> None:
            if process.poll() is None:
                overran.set()
                _asked_to_stop(
                    process, f"it ran out of its {self.seconds / 60:.0f} minutes"
                )

        alarm = threading.Timer(self.seconds, ran_out)
        alarm.daemon = True
        alarm.start()

        # When anything last appeared that a person watching would have
        # seen. Not when a line last arrived: a worker whose connection has
        # stalled still has keepalives coming down the pipe, so by that
        # measure it is talking, and one sat at under one percent of a
        # processor for six minutes looking perfectly healthy. A worker that
        # has shown nothing has stopped working, whatever the pipe says.
        showed_at = [time.monotonic()]
        quiet = threading.Event()
        silent = threading.Event()

        def still_there() -> None:
            while not quiet.wait(QUIET_EVERY):
                unseen = time.monotonic() - showed_at[0]
                if unseen >= SILENT_LIMIT and process.poll() is None:
                    silent.set()
                    _asked_to_stop(process, "it showed nothing for five minutes")
                    return
                if unseen >= QUIET_AFTER and on_event:
                    left = self.seconds - (time.monotonic() - began)
                    on_event(
                        "engine",
                        f"still working - {int(unseen // 60)}m "
                        f"{int(unseen % 60):02d}s on one step, "
                        f"{max(0, int(left // 60))}m left on the clock",
                    )

        began = time.monotonic()
        heartbeat = threading.Thread(target=still_there, daemon=True)
        heartbeat.start()

        dollars, turns, counted = 0.0, 0, 0
        try:
            for line in process.stdout:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # A field present but null is not a number. The worker's
                # output is a wire format from another program and the only
                # safe assumption about it is that it is JSON.
                if isinstance(event.get("total_cost_usd"), int | float):
                    dollars = event["total_cost_usd"]
                # The worker reports its own turn count, but only in the
                # final message - so a worker that was stopped reported nought
                # turns after twelve minutes of visible work, which is both
                # wrong and the opposite of useful. Count them here as well
                # and keep whichever is larger.
                if event.get("type") == "assistant":
                    counted += 1
                said_turns = event.get("num_turns")
                turns = max(
                    turns,
                    said_turns if isinstance(said_turns, int) else 0,
                    counted,
                )
                # Reported whether or not anybody is listening: with no
                # listener the clock above would never move and a worker
                # would be stopped five minutes in for working quietly.
                if _report(event, on_event or _nobody):
                    showed_at[0] = time.monotonic()
        finally:
            alarm.cancel()
            quiet.set()

        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
        _forget(process)
        # Which clock reached it first is the difference between "this item
        # is too large" and "this worker stopped working", so the caller is
        # told which rather than that one of them did.
        if silent.is_set():
            return dollars, turns, "silence"
        return dollars, turns, "clock" if overran.is_set() else ""

    def structured(
        self,
        repo: Path,
        system: str,
        prompt: str,
        shape: str,
        read_only: bool = True,
        on_event=None,
        tools: str | None = None,
        without: str = "",
    ) -> tuple[dict, float, int]:
        """Ask for an answer in a given shape, and get it as a file.

        Claude Code answers in prose, and parsing prose is how an agent
        pipeline starts producing confident nonsense. Having it write a JSON
        file instead means the answer either validates or visibly does not.
        """
        out = repo / ".drydock-out.json"
        out.unlink(missing_ok=True)

        instruction = (
            f"{prompt}\n\nWrite your answer to .drydock-out.json in the repository "
            f"root as exactly this JSON and nothing else:\n{shape}\n"
            "Write no other file and change nothing else."
        )
        # `tools` is the allowance; `without` is the refusal. Both are needed,
        # because naming the allowed tools only pre-approves them - it does
        # not stop the worker reaching for something else. A reviewer given
        # the diff in its prompt went and read the files anyway, then ran the
        # test suite, and was cut off before it could answer.
        tools = (
            tools
            if tools is not None
            else ("Read Glob Grep" + ("" if read_only else " Edit Write"))
        )
        command = [
            self.binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--max-turns",
            str(self.max_turns),
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            f"{tools} Write(.drydock-out.json)".strip(),
            *(["--disallowedTools", without] if without else []),
            "--append-system-prompt",
            system,
        ]
        settings, env = _confinement(repo)
        command[1:1] = ["--settings", settings]

        process = subprocess.Popen(
            command,
            cwd=repo,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            # Its own session, so that nothing can take it down by
            # signalling a group. Started as an ordinary child it sits in
            # this application's process group along with every preview
            # server, and anything in there that cleans up after itself by
            # signalling the group - which is what npm does - stops the
            # worker too. A healthy one died twice this way, mid-sentence,
            # with no clock of ours anywhere near it. The preview already
            # ran in its own session; the workers did not.
            start_new_session=True,
        )
        process.drydock_repo = str(repo)
        _watch(process)
        process.stdin.write(instruction)
        process.stdin.close()

        dollars, turns, overran = self._read(process, on_event)
        if overran and on_event:
            on_event("engine", _why_it_stopped(overran, self.seconds))
        _forget(process)

        if not out.exists():
            why = (process.stderr.read() or "").strip()[-1200:]
            raise EngineUnavailable(
                "the worker stopped without writing an answer"
                + (f" (exit {process.returncode})" if process.returncode else "")
                + (f".\n\n{why}" if why else ".")
            )
        payload = json.loads(out.read_text())
        out.unlink(missing_ok=True)
        return payload, dollars, turns


def _was_killed(code: int | None) -> bool:
    """Whether a worker was taken away rather than deciding to stop.

    A process killed by a signal reports a negative code here, and one whose
    own runtime caught the signal and exited reports 128 plus the number -
    which is what the worker does. Either way nobody asked it to stop and
    the item it was given has not been tried.
    """
    if code is None:
        return False
    return code < 0 or 128 < code < 160


def _why_it_stopped(which: str, seconds: float) -> str:
    if which == "silence":
        return f"stopped - nothing at all for {SILENT_LIMIT // 60} minutes"
    return f"stopped after {seconds / 60:.0f} minutes"


def _nobody(kind: str, text: str) -> None:
    """A listener for when there is none."""


def _report(event: dict, on_event) -> bool:
    """Turn one stream-json line into the same shape the API engine emits.

    Returns whether anything was actually passed on. Most lines are not
    something a person would see: a long turn streams steadily and shows
    nothing, which is the difference between a worker being alive and a
    worker appearing to do anything.
    """
    shown = False
    kind = event.get("type")
    if kind == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                detail = ", ".join(
                    f"{k}={str(v)[:50]}"
                    for k, v in list(block.get("input", {}).items())[:2]
                )
                on_event("tool", f"{block.get('name')} {detail}")
                shown = True
            elif block.get("type") == "text" and block.get("text", "").strip():
                on_event("thinking", block["text"].strip())
                shown = True
    elif kind == "result":
        on_event("done", "worker finished")
        shown = True
    return shown
