"""The Engineer: do one item, and only that item.

The scope rule is the whole discipline here. An agent asked to migrate a test
suite will wander: it notices a typo, a dead import, a test that could be
clearer, and fixes them, and the diff that was meant to prove one idea now
contains six. When the suite then goes red, nothing points at a cause.

So the item is the contract. Anything outside it that deserves attention is
reported, not fixed.
"""

from pathlib import Path

from .agent import Agent, Tool
from .models import Item
from .skills import Skill, briefing
from .tools import write_tools

SYSTEM = """You are making one change to a codebase that currently works.

The item you are given is the entire scope. Not the task it belongs to, not the
next item, not something adjacent that is obviously wrong. If you find a real
problem outside the item, say so in your report and leave it alone.

How to work:

Read before you write. The text you pass to replace_in_file has to match the
file exactly, so read the part you are about to change.

Compile as you go. The build tool is there to catch your mistakes while they
are still cheap, not to be run once at the end.

Prefer narrow edits. replace_in_file with an expected count fails loudly when
a pattern appears more often than you thought, which is the moment you want to
know. write_file replaces a whole file and hides that.

Do not touch the verification. Changing a test so it passes, loosening an
assertion, or skipping a case is a failure of this job, not a solution to it.
If the item cannot be done as written, report that instead."""

PROMPT = """Repository: {repo}
Build: {build_command}

Overall task, for context only:
{task}

Your item, which is the entire scope:

  {id}. {title}

  {rationale}

  files: {files}
  verified by: {verify_with}

Make the change, then report."""


def _report_tool() -> Tool:
    return Tool(
        name="report",
        description="Report what you did. Call this once, when the item is finished.",
        schema={
            "type": "object",
            "properties": {
                "done": {
                    "type": "boolean",
                    "description": "False if the item could not be done as written.",
                },
                "summary": {
                    "type": "string",
                    "description": "What changed, in one or two sentences.",
                },
                "files_changed": {"type": "array", "items": {"type": "string"}},
                "noticed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Problems outside this item's scope, left alone.",
                },
            },
            "required": ["done", "summary", "files_changed", "noticed"],
            "additionalProperties": False,
        },
        run=lambda **_: "",
        strict=True,
    )


def work(
    repo: Path,
    task: str,
    item: Item,
    build_command: str,
    retry_of: str = "",
    skills: list[Skill] | None = None,
    on_event=None,
) -> tuple[dict, object]:
    prompt = PROMPT.format(
        repo=repo.name,
        build_command=build_command,
        task=task,
        id=item.id,
        title=item.title,
        rationale=item.rationale,
        files=", ".join(item.files),
        verify_with=item.verify_with,
    )
    if retry_of:
        prompt += (
            "\n\nThis item was attempted and the verification failed. The output "
            f"is below. Work out what broke before changing anything else.\n\n{retry_of}"
        )

    agent = Agent(
        name="Engineer",
        system=SYSTEM + briefing(skills or [], "engineer"),
        tools=write_tools(repo, build_command),
        max_turns=40,
        on_event=on_event,
    )
    return agent.run(prompt, final_tool=_report_tool()), agent.usage
