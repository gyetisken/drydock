"""Read-only tools.

The Analyst and the Planner are given these and nothing else. Neither of them
writes a file or runs a build; they look, and then they say what they found.
Keeping the reading agents unable to change anything means a wrong conclusion
costs a wrong plan, which a person still has to approve, rather than a wrong
edit that is already on disk.
"""

from pathlib import Path

from .agent import Tool
from .shell import run

MAX_OUTPUT = 12000

# Build output is not source. Left in, the agent reads surefire reports and
# compiled classes and draws conclusions from yesterday's artefacts.
IGNORED = ("target", "build", "dist", "node_modules", ".git", ".venv", "__pycache__")


def _inside(repo: Path, target: str) -> Path:
    """Refuse anything that climbs out of the repository."""
    resolved = (repo / target).resolve()
    if not str(resolved).startswith(str(repo.resolve())):
        raise ValueError(f"{target} is outside the repository")
    return resolved


def read_only(repo: Path) -> list[Tool]:
    excludes = " ".join(f"--exclude-dir={name}" for name in IGNORED)

    def grep(pattern: str, path: str = ".") -> str:
        code, out = run(
            f"grep -rn {excludes} --include=*.* -m 400 -- {pattern!r} {path}",
            repo,
            timeout=60,
        )
        if code == 1:
            return "no matches"
        return out[:MAX_OUTPUT]

    def list_files(path: str = ".", depth: int = 2) -> str:
        pruned = " ".join(f"-not -path '*/{name}/*'" for name in IGNORED)
        code, out = run(f"find {path} -maxdepth {depth} {pruned}", repo, 60)
        return out[:MAX_OUTPUT]

    def read_file(path: str, start: int = 1, lines: int = 200) -> str:
        if any(part in IGNORED for part in Path(path).parts):
            return f"{path}: build output, not source. Read the sources instead."
        target = _inside(repo, path)
        if not target.is_file():
            return f"{path}: not a file"
        body = target.read_text(errors="replace").splitlines()
        chunk = body[start - 1 : start - 1 + lines]
        numbered = "\n".join(f"{i:>5} {line}" for i, line in enumerate(chunk, start))
        return f"{path} ({len(body)} lines)\n{numbered}"[:MAX_OUTPUT]

    return [
        Tool(
            name="grep",
            description="Search the repository for a pattern. Returns file:line matches.",
            schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {
                        "type": "string",
                        "description": "defaults to the repo root",
                    },
                },
                "required": ["pattern"],
            },
            run=grep,
        ),
        Tool(
            name="list_files",
            description="List files under a path.",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "depth": {"type": "integer"},
                },
                "required": [],
            },
            run=list_files,
        ),
        Tool(
            name="read_file",
            description="Read part of a file, with line numbers.",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start": {"type": "integer", "description": "first line, 1-based"},
                    "lines": {"type": "integer"},
                },
                "required": ["path"],
            },
            run=read_file,
        ),
    ]


def write_tools(repo: Path, build_command: str) -> list[Tool]:
    """Read-only tools plus the ability to change files and compile.

    The Engineer gets no shell. It can edit files and it can run one command,
    the project's own build, so it can see a compile error and fix it without
    a round trip through the orchestrator. Everything else it might want to run
    it cannot: the cost of a loop that can run anything is unbounded, and the
    cost of one that can only compile is a few seconds.
    """

    def write_file(path: str, content: str) -> str:
        target = _inside(repo, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content)
        lines = content.count("\n") + 1
        return f"{'rewrote' if existed else 'created'} {path}, {lines} lines"

    def replace_in_file(path: str, find: str, replace: str, count: int = 0) -> str:
        """Exact-text replacement. No regex, so nothing surprising matches."""
        target = _inside(repo, path)
        if not target.is_file():
            return f"{path}: not a file"
        body = target.read_text()
        hits = body.count(find)
        if hits == 0:
            return f"{path}: no occurrence of that text. Read the file and match it exactly."
        if count and hits > count:
            return f"{path}: {hits} occurrences but {count} expected. Narrow the text."
        target.write_text(body.replace(find, replace))
        return f"{path}: replaced {hits} occurrence{'s' if hits != 1 else ''}"

    def build() -> str:
        code, out = run(build_command, repo, timeout=900)
        head = "build ok" if code == 0 else f"build FAILED (exit {code})"
        return f"{head}\n{out[-6000:]}"

    return read_only(repo) + [
        Tool(
            name="write_file",
            description="Write a file, replacing it entirely. Prefer replace_in_file for edits.",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            run=write_file,
        ),
        Tool(
            name="replace_in_file",
            description=(
                "Replace exact text in a file. The text must match the file "
                "character for character, including indentation."
            ),
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                    "count": {
                        "type": "integer",
                        "description": "Expected number of occurrences; refuses if there are more.",
                    },
                },
                "required": ["path", "find", "replace"],
            },
            run=replace_in_file,
        ),
        Tool(
            name="build",
            description="Compile the project. Use it to check your work as you go.",
            schema={"type": "object", "properties": {}, "required": []},
            run=build,
        ),
    ]
