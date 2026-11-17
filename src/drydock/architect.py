"""Deciding the shape of something that does not exist yet.

On an existing repository the shape is already there to be read, and the
Analyst reads it. On an empty one there is nothing to read, and a planner given
an empty repository and a sentence will invent a stack somewhere in the middle
of writing item four. That decision is then implicit: never stated, never
questioned, and visible only as whatever the first file happened to import.

This station makes it explicit and makes it first. It answers the questions
that everything after depends on - what this is built with, what the pieces
are, and what the first failing test is - and it answers them before anyone has
written a line, which is when changing the answer is still free.

The first test matters more than the stack. A project whose suite runs and
fails is a project with a working test command, and from then on every later
item can be verified. A project whose first item is a feature has no way to
tell whether item two broke item one.
"""

from pathlib import Path

from .agent import API_MODEL, JUDGEMENT, Agent, Tool
from .engines import ClaudeCodeEngine
from .skills import Skill, briefing
from .tools import read_only

SYSTEM = """You decide the shape of a project that does not exist yet.

Pick the plainest thing that works. A stack somebody can run with one command
beats a stack that is fashionable, and a reader who knows the language should
not have to learn your layout before they can find anything.

Three rules hold whatever is being built:

- The test command comes first and it must fail on an empty suite. A runner
  that reports success having found no tests is worse than no runner, because
  everything after it is verified against nothing.
- One command to run it. If someone has to read a wiki to start it, it is not
  finished.
- Nothing downloaded or generated goes into the repository. Whatever the
  package manager puts on disk must be ignored before it is installed, not
  cleaned up afterwards.
- Name the pieces by what they do, not by what they are. A folder called
  `utils` is a folder nobody can describe.

Do not plan the work. Say what it is made of and what the first test proves."""

PROMPT = """Build this: {task}

The repository is {state}.

Decide the shape. Be specific enough that someone could start: name the
language and version, the framework if there is one, how it is run, how it is
tested, and what the first test asserts. Keep the first version small enough
that it actually works end to end."""


def _tool() -> Tool:
    return Tool(
        name="design",
        description="State the shape of the project.",
        schema={
            "type": "object",
            "properties": {
                "stack": {
                    "type": "string",
                    "description": "Language, version, framework, and why this one.",
                },
                "run_command": {"type": "string"},
                "test_command": {
                    "type": "string",
                    "description": "Must fail on an empty suite.",
                },
                "pieces": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The parts, each named by what it does.",
                },
                "first_test": {
                    "type": "string",
                    "description": "What the very first test asserts, in one sentence.",
                },
                "not_doing": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "What is deliberately left out of the first version.",
                },
            },
            "required": [
                "stack",
                "run_command",
                "test_command",
                "pieces",
                "first_test",
                "not_doing",
            ],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


def design(
    repo: Path,
    task: str,
    skills: list[Skill] | None = None,
    on_event=None,
    budget: float = 0.0,
    engine: str = "api",
    model: str = "opus",
) -> tuple[dict, object]:
    existing = [p.name for p in repo.iterdir() if p.name != ".git"][:12]
    prompt = PROMPT.format(
        task=task,
        state="empty" if not existing else f"nearly empty: {', '.join(existing)}",
    )
    system = SYSTEM + briefing(skills or [], "plan")

    if engine == "claude":
        found, dollars, turns = ClaudeCodeEngine(model=model, max_turns=6).structured(
            repo,
            system,
            prompt,
            '{"stack": "...", "run_command": "...", "test_command": "...", '
            '"pieces": ["..."], "first_test": "...", "not_doing": ["..."]}',
            on_event=on_event,
        )
        return found, _Spend(dollars, turns)

    agent = Agent(
        name="Architect",
        model=API_MODEL.get(model, JUDGEMENT),
        system=system,
        tools=read_only(repo),
        max_turns=6,
        budget=budget,
        on_event=on_event,
    )
    return agent.run(prompt, final_tool=_tool()), agent.usage


def as_briefing(found: dict) -> str:
    """What the planner is handed. Empty when there was no design to make."""
    if not found:
        return ""
    return (
        "\n\nThe shape of this project has already been decided, and the plan "
        "has to build that rather than something else:\n\n"
        f"- Built with: {found.get('stack', '')}\n"
        f"- Run with: `{found.get('run_command', '')}`\n"
        f"- Tested with: `{found.get('test_command', '')}`, which must fail on "
        "an empty suite\n"
        f"- Made of: {', '.join(found.get('pieces', []))}\n"
        f"- The first test asserts: {found.get('first_test', '')}\n"
        f"- Deliberately not in the first version: "
        f"{', '.join(found.get('not_doing', [])) or 'nothing stated'}\n\n"
        "The first item is the one that makes the test command exist and fail "
        "on an empty suite. Nothing can be verified before it."
    )


class _Spend:
    def __init__(self, dollars: float, turns: int) -> None:
        self.input_tokens = self.output_tokens = self.cached_tokens = 0
        self.turns = turns
        self.dollars = dollars
