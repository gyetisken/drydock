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
import shutil
import subprocess
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
    dollars: float = 0.0
    turns: int = 0


class ClaudeCodeEngine:
    """Drive the Claude Code CLI as the worker.

    It already has file tools, a shell, and an account. What it does not have
    is a reason to stop, so the bounds come from here: the directory it may
    touch, the commands it may run, and the number of turns it may take.
    """

    name = "claude"

    def __init__(self, model: str = "opus", max_turns: int = 40) -> None:
        self.binary = shutil.which("claude")
        if not self.binary:
            raise EngineUnavailable(
                "the `claude` command is not on PATH. Install Claude Code and "
                "sign in, or use the API engine with a key."
            )
        self.model = model
        self.max_turns = max_turns

    def work(
        self,
        repo: Path,
        system: str,
        prompt: str,
        build_command: str,
        on_event=None,
    ) -> EngineResult:
        build_tool = build_command.split()[0]
        report_file = repo / ".drydock-report.json"
        report_file.unlink(missing_ok=True)

        instruction = (
            f"{prompt}\n\n"
            "When the item is finished, write a file at .drydock-report.json in "
            "the repository root containing exactly this JSON and nothing else:\n"
            '{"done": true, "summary": "...", "files_changed": ["..."], '
            '"noticed": ["..."]}\n'
            "Set done to false if the item could not be done as written. Put "
            "anything outside the item's scope into noticed rather than fixing it."
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
            f"Read Edit Write Glob Grep Bash({build_tool} *)",
            "--append-system-prompt",
            system,
        ]

        process = subprocess.Popen(
            command,
            cwd=repo,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        process.stdin.write(instruction)
        process.stdin.close()

        dollars, turns = 0.0, 0
        for line in process.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            dollars = event.get("total_cost_usd", dollars)
            turns = event.get("num_turns", turns)
            if on_event:
                _report(event, on_event)
        process.wait(timeout=60)

        if not report_file.exists():
            return EngineResult(
                done=False,
                summary="the worker finished without writing a report",
                files_changed=[],
                noticed=[],
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
            dollars=dollars,
            turns=turns,
        )

    def structured(
        self,
        repo: Path,
        system: str,
        prompt: str,
        shape: str,
        read_only: bool = True,
        on_event=None,
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
        tools = "Read Glob Grep" + ("" if read_only else " Edit Write")
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
            f"{tools} Write(.drydock-out.json)",
            "--append-system-prompt",
            system,
        ]

        process = subprocess.Popen(
            command,
            cwd=repo,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        process.stdin.write(instruction)
        process.stdin.close()

        dollars, turns = 0.0, 0
        for line in process.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            dollars = event.get("total_cost_usd", dollars)
            turns = event.get("num_turns", turns)
            if on_event:
                _report(event, on_event)
        process.wait(timeout=60)

        if not out.exists():
            raise EngineUnavailable(
                "the worker finished without writing an answer. Try the API "
                "engine, or run the same command again."
            )
        payload = json.loads(out.read_text())
        out.unlink(missing_ok=True)
        return payload, dollars, turns


def _report(event: dict, on_event) -> None:
    """Turn one stream-json line into the same shape the API engine emits."""
    kind = event.get("type")
    if kind == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                detail = ", ".join(
                    f"{k}={str(v)[:50]}"
                    for k, v in list(block.get("input", {}).items())[:2]
                )
                on_event("tool", f"{block.get('name')} {detail}")
            elif block.get("type") == "text" and block.get("text", "").strip():
                on_event("thinking", block["text"].strip())
    elif kind == "result":
        on_event("done", "worker finished")
