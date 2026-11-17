"""The slash commands.

Most of them come from the installed skills, because a skill already knows
what it is for and what to ask. Registering commands separately would mean two
places to keep in step, and the second one would be the one that rots.

A handful are built in, for work that is not a skill: running a task with no
packaged knowledge behind it, and looking at what is installed.
"""

from dataclasses import dataclass
from pathlib import Path

from .skills import Skill, discover

# The crew is a line of four stations and each one needs the one before it.
# A command says where it stops, never where it starts: asking for a plan runs
# the survey first, because a plan written without reading the repository is
# the thing this is meant to prevent.
STAGES = ["baseline", "analyst", "planner", "engineer"]


@dataclass(frozen=True)
class Command:
    name: str
    summary: str
    asks: str = ""
    skill: Skill | None = None
    task_template: str = ""
    stop_after: str = "planner"

    @property
    def stages(self) -> list[str]:
        return STAGES[: STAGES.index(self.stop_after) + 1]

    def task_for(self, answer: str) -> str:
        if not self.task_template:
            return answer
        if "{what}" in self.task_template:
            return self.task_template.format(what=answer.strip())
        return self.task_template


BUILT_IN = [
    Command(
        name="/check",
        summary="Build it and run the suite. No model, no changes, no cost.",
        task_template="Report the health of this repository as it stands.",
        stop_after="baseline",
    ),
    Command(
        name="/audit",
        summary="Read the project and report what is fragile. Nothing is changed.",
        task_template=(
            "Survey this repository and report what is fragile: what would break "
            "first, what is untested, what is coupled to something it should not "
            "be. Change nothing."
        ),
        stop_after="analyst",
    ),
    Command(
        name="/plan",
        summary="Work out how a change would be made, and stop before making it.",
        asks="what you are considering",
        task_template="{what}",
        stop_after="planner",
    ),
    Command(
        name="/do",
        summary="Describe a change in your own words. No packaged knowledge, just the crew.",
        asks="what you want changed",
    ),
]


def available(skills_root: Path) -> list[Command]:
    commands = list(BUILT_IN)
    for skill in discover(skills_root) if skills_root.exists() else []:
        if not skill.command:
            continue
        commands.append(
            Command(
                name=skill.command,
                summary=skill.description,
                asks=skill.asks,
                skill=skill,
                task_template=skill.task,
            )
        )
    return sorted(commands, key=lambda c: c.name)


def match(text: str, commands: list[Command]) -> tuple[Command | None, str]:
    """Split typed text into the command and whatever followed it."""
    text = text.strip()
    if not text.startswith("/"):
        return None, text
    head, _, rest = text.partition(" ")
    for command in commands:
        if command.name == head:
            return command, rest.strip()
    return None, text


def suggest(prefix: str, commands: list[Command]) -> list[Command]:
    prefix = prefix.strip().lower()
    if not prefix.startswith("/"):
        return []
    return [c for c in commands if c.name.startswith(prefix)]
