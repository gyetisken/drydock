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
import shlex
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


class MalformedAnswer(RuntimeError):
    """The worker answered, and what it wrote is not the shape asked for.

    Kept apart from EngineUnavailable because the two call for opposite
    responses. A worker that never answered has told you nothing and the
    machine may be at fault; one that wrote an answer you cannot read has
    done the work and lost it on the way out, and asking the same question
    again usually gets a readable answer for a fraction of the cost.

    A critic's verdict was lost this way: it rendered the page, read both
    images, judged them and wrote `{"approved": true, "reason": "..."}`
    with an unescaped character two and a half thousand characters in. The
    parse failed, the exception was caught as "could not look at it", no
    gate decision was recorded, and the item shipped without the one
    station that can see having been heard.
    """

    def __init__(self, why: str, text: str = "") -> None:
        super().__init__(why)
        # What it actually wrote, for the report and for one repair.
        self.text = text


def _claude_binary() -> str:
    binary = shutil.which("claude")
    if not binary:
        raise EngineUnavailable(
            "the `claude` command is not on PATH. Install Claude Code and "
            "sign in, or use the API engine with a key."
        )
    return binary


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


# The one command that lets a worker see what it just built. Not a shell
# and not a browser: it starts the project the way the project says it
# starts, measures the page, writes two pictures into the tree and prints
# what it found. The path it is given is validated as a path - no scheme,
# no host, no port - so there is nowhere for it to go but this project.
LOOK = "drydock-look"


def _shell_rule(build_command: str, can_look: bool = False) -> str:
    """Which shell commands the worker may run.

    Once a project has a build command the worker is held to it, which is as
    narrow as this gets. Before then it would be held to nothing, and the
    earlier version of this line simply crashed on the empty string - which
    is how greenfield jobs died the moment they reached the first item.
    """
    tool = build_command.split()[0] if build_command.strip() else ""
    if tool:
        allowed = [f"Bash({tool} *)"]
    else:
        allowed = [f"Bash({name} *)" for name in BOOTSTRAP]
    if can_look:
        # Both forms: it is useful with no argument at all, which is the
        # home page, and with one path.
        allowed += [f"Bash({LOOK})", f"Bash({LOOK} *)"]
    return " ".join(allowed)


# A two-line script rather than a console entry point, because drydock is
# as often a checkout as an installation and `drydock-look` has to work the
# same either way. Written outside every repository: it is ours, and a tool
# that appears in somebody's project is a file they have to explain.
def _put_the_tool_somewhere(env: dict) -> Path:
    """Write the look command where a worker can run it, and return its dir."""
    home = Path(os.environ.get("DRYDOCK_HOME") or Path.home() / ".drydock")
    where = home / "bin"
    where.mkdir(parents=True, exist_ok=True)
    tool = where / LOOK
    # This interpreter, not whatever `python3` resolves to on the worker's
    # path. PYTHONPATH is already set below for the confinement hook, which
    # is what makes the import work from a checkout.
    wanted = f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -m drydock.look "$@"\n'
    if not tool.exists() or tool.read_text() != wanted:
        tool.write_text(wanted)
    tool.chmod(0o755)
    return where


def shell_allowance(build_command: str) -> str:
    """What the engineer may run, said in words rather than as a rule.

    Derived from `_shell_rule` rather than written beside it, because the
    two drifting apart is how a worker comes to believe something it was
    allowed to do is forbidden.

    One did. Its first Bash call succeeded, four `node --check` calls were
    refused with "this command requires approval" - `node` is not the
    build tool - and it concluded "Bash isn't permitted here" and finished
    the item without ever running `npm test`, which it was allowed to run
    the whole time. The refusal never says what is allowed, so the worker
    can only learn the fence by walking into it.
    """
    tool = build_command.split()[0] if build_command.strip() else ""
    if tool:
        return (
            f"Through the shell you may run `{tool}` and nothing else - "
            f"`{build_command}` is the command this project is built and "
            f"checked with. Anything else is refused. A refusal is this "
            f"fence and not a sign that the shell is unavailable: if one "
            f"command is turned down, `{tool}` still works."
        )
    return (
        "This project has no build command yet, so through the shell you "
        "may run the tools that bring one into existence - "
        + ", ".join(f"`{name}`" for name in BOOTSTRAP[:8])
        + " and a few more like them - and nothing else. Anything else is "
        "refused. A refusal is that fence and not a sign that the shell is "
        "unavailable."
    )


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
# Measured against partial output - fragments of words as the model writes
# them - which is the only signal that separates a worker writing a long
# file from one whose connection has stalled. Two minutes of producing
# nothing at all is the second.
SILENT_LIMIT = 120

# How recently a worker must have shown something for its clock to be
# extended rather than enforced. Shorter than the silence limit on purpose:
# anything quieter than this is already on its way to being stopped.
STILL_GOING = 60

_WORKERS: set[subprocess.Popen] = set()
_WORKERS_LOCK = threading.Lock()

# Every signal this program sends a worker, by pid. A worker that died of a
# signal nobody here sent is a different problem from one this program
# stopped on purpose, and for two days the two were indistinguishable from
# the outside - an item would simply end with "exited 143" and no account of
# who asked. Writing it down is cheap and turns a mystery into a fact.
_SIGNALLED: dict[int, str] = {}


# How long a worker gets to honour a polite stop before it is killed.
# Asking first is right: a worker given a moment closes its own files. But
# asking was all this did, and a worker that does not honour the signal
# simply carried on - two items ran for a hundred and fifty-four minutes
# against a twelve-minute clock, because the clock fired, asked once, and
# then waited for a process that was busy retrying a network call.
GRACE = 10


def _asked_to_stop(process, why: str) -> None:
    """Stop a worker, and remember that it was us who asked.

    Asked, then told. The telling runs on its own thread because the
    thread that notices is often the one reading the worker's output, and
    that read is exactly what will not return.
    """
    pid = getattr(process, "pid", None)
    if pid is not None:
        _SIGNALLED[pid] = why
    try:
        process.terminate()
    except OSError:
        return

    def insist() -> None:
        # Everything here runs on a daemon thread, where an exception is
        # printed to nobody and the worker is never killed. Guarded rather
        # than trusted.
        try:
            if process.poll() is not None:
                return
            process.kill()
        except (OSError, AttributeError):
            pass

    alarm = threading.Timer(GRACE, insist)
    alarm.daemon = True
    alarm.start()


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


def _belongs_to(where: str, repo: Path) -> bool:
    """Whether a worker working in `where` belongs to a run in `repo`.

    Not just the repository path. A wave works each item in a worktree
    under drydock's own directory, named after the repository, so matching
    only `str(repo)` found the workers of a single-item run and none of a
    parallel one - which is how stopping a run left three engineers
    writing into worktrees it was about to remove.
    """
    if not where:
        return False
    if where == str(repo):
        return True
    home = Path(os.environ.get("DRYDOCK_HOME") or Path.home() / ".drydock")
    return where.startswith(str(home / "worktrees" / f"{repo.name}-"))


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
        if repo is None or _belongs_to(str(said.get("repo") or ""), repo):
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
            and (
                repo is None
                or _belongs_to(str(getattr(p, "drydock_repo", "") or ""), repo)
            )
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


def _but_not_the_answer(without: str) -> str:
    """Whatever a station refuses, it cannot refuse the file it answers in.

    The answer comes back through `Write(.drydock-out.json)`, appended to
    what is allowed a line above this. A station that also lists `Write`
    among the tools it does not want leaves a worker that can read the
    repository, run commands, and has nowhere to put what it found: it
    talks to itself until the turn limit and exits without an answer.

    Written twice before it was caught twice - once in the start call,
    where it span for three minutes, and once in the answering path, where
    saying hello came back as `EngineUnavailable: the worker stopped
    without writing an answer (exit 1)`. The second time is what made it
    the engine's business rather than each caller's.
    """
    return " ".join(t for t in without.split() if t != "Write")


def _confinement(repo: Path, look_key: str = "", looks: int = 0) -> tuple[str, dict]:
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
    if looks > 0 and look_key:
        # The budget travels in the environment rather than in the prompt,
        # because the prompt is something the worker can argue with. The
        # tally itself is kept under the drydock home, outside what the
        # worker's file tools may touch, and it is keyed by run and item so
        # that items sharing a tree cannot spend each other's looks.
        env["PATH"] = str(_put_the_tool_somewhere(env)) + os.pathsep + env["PATH"]
        env["DRYDOCK_LOOK_KEY"] = look_key
        env["DRYDOCK_LOOK_LIMIT"] = str(looks)
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
        look_key: str = "",
        looks: int = 0,
    ) -> EngineResult:
        binary = _claude_binary()
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
            binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            # Partial chunks as they are produced. Nothing here is shown to
            # anybody - a half-written sentence is not progress somebody can
            # read - but they are the only way to tell a worker that is
            # writing a long file from one whose connection has stalled.
            # Both look identical otherwise: no tool call, no text block, no
            # result, for minutes.
            "--include-partial-messages",
            "--model",
            self.model,
            "--max-turns",
            str(self.max_turns),
            "--permission-mode",
            "acceptEdits",
            # Bounded on purpose: it may read, edit and run the project's own
            # build, and nothing else. Without this it has a shell.
            "--allowedTools",
            "Read Edit Write Glob Grep "
            + _shell_rule(build_command, can_look=looks > 0 and bool(look_key)),
            "--append-system-prompt",
            system,
        ]
        settings, env = _confinement(repo, look_key=look_key, looks=looks)
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
        # When anything last appeared that a person watching would have
        # seen. Not when a line last arrived: a worker whose connection has
        # stalled still has keepalives coming down the pipe, so by that
        # measure it is talking. Declared here rather than beside the other
        # clocks because the alarm below reads it, and a short clock in a
        # test would otherwise fire before it existed.
        showed_at = [time.monotonic()]

        overran = threading.Event()
        extended = [False]

        def ran_out() -> None:
            if process.poll() is not None:
                return
            # A worker that is still producing when its time runs out has
            # not failed; it has run out of budget. An item was stopped at
            # twelve minutes having got through thirty-nine turns, and
            # every file it had written was thrown away. One extension,
            # once, and only for a worker that is visibly working - a
            # stalled one is caught two minutes in by the silence limit and
            # must not be given more time to be stalled in.
            working = time.monotonic() - showed_at[0] < STILL_GOING
            if working and not extended[0]:
                extended[0] = True
                if on_event:
                    on_event(
                        "engine",
                        f"{self.seconds / 60:.0f} minutes gone and still "
                        f"working - {self.seconds / 120:.0f} more, once",
                    )
                later = threading.Timer(self.seconds / 2, ran_out)
                later.daemon = True
                later.start()
                return
            overran.set()
            _asked_to_stop(
                process, f"it ran out of its {self.seconds / 60:.0f} minutes"
            )

        alarm = threading.Timer(self.seconds, ran_out)
        alarm.daemon = True
        alarm.start()

        # Two clocks, and the difference between them is the difference
        # between a worker that is busy and a worker that is stuck.
        #
        # `working_at` is the last sign the model was producing anything at
        # all, down to a fragment of a word. A worker writing a long file
        # moves it constantly; one whose connection has stalled does not
        # move it at any point, which is the only honest way to tell the two
        # apart - from the outside they are identical, with no tool call, no
        # text and no result for minutes.
        #
        # `showed_at` is the last thing a person watching would have seen,
        # which is what the message below is about. Both were once the same
        # clock, and either choice alone is wrong: watching only the raw
        # pipe kept a stalled worker alive for six minutes, and killing on
        # nothing-shown would stop a worker halfway through writing a
        # stylesheet.
        working_at = [time.monotonic()]
        quiet = threading.Event()
        silent = threading.Event()

        def still_there() -> None:
            while not quiet.wait(QUIET_EVERY):
                stuck = time.monotonic() - working_at[0]
                unseen = time.monotonic() - showed_at[0]
                if stuck >= SILENT_LIMIT and process.poll() is None:
                    silent.set()
                    _asked_to_stop(
                        process, f"it produced nothing for {int(stuck)} seconds"
                    )
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
                working_at[0] = time.monotonic()
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
        binary = _claude_binary()
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
            binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            # Partial chunks as they are produced. Nothing here is shown to
            # anybody - a half-written sentence is not progress somebody can
            # read - but they are the only way to tell a worker that is
            # writing a long file from one whose connection has stalled.
            # Both look identical otherwise: no tool call, no text block, no
            # result, for minutes.
            "--include-partial-messages",
            "--model",
            self.model,
            "--max-turns",
            str(self.max_turns),
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            f"{tools} Write(.drydock-out.json)".strip(),
            *(["--disallowedTools", _but_not_the_answer(without)] if without else []),
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
        written = out.read_text()
        out.unlink(missing_ok=True)
        try:
            payload = json.loads(written)
        except ValueError as exc:
            raise MalformedAnswer(
                f"the worker wrote an answer that is not valid JSON: {exc}",
                written,
            ) from exc
        if not isinstance(payload, dict):
            raise MalformedAnswer(
                f"the worker wrote {type(payload).__name__} where an object was asked for",
                written,
            )
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
