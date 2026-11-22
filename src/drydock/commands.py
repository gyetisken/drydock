"""The slash commands.

Most of them come from the installed skills, because a skill already knows
what it is for and what to ask. Registering commands separately would mean two
places to keep in step, and the second one would be the one that rots.

A handful are built in, for work that is not a skill: running a task with no
packaged knowledge behind it, and looking at what is installed.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from .skills import Skill, discover

# The crew is a line of four stations and each one needs the one before it.
# A command says where it stops, never where it starts: asking for a plan runs
# the survey first, because a plan written without reading the repository is
# the thing this is meant to prevent.
STAGES = ["baseline", "analyst", "planner", "engineer"]

# Work that is not a stage of that line: it reads, says something, and
# stops. Kept as a set because two places ask the same question of it.
ALONE = ("ask", "review", "qa")


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
        # Two commands are not stages of the line at all. `/ask` answers and
        # `/review` reads; neither starts at the baseline and neither ends
        # anywhere in STAGES.
        #
        # This list and `Session._stages` say the same thing in two places,
        # and when `/review` was added to one and not the other this raised
        # ValueError on every call to `GET /api/state` - which is to say the
        # window would not load at all.
        if self.stop_after in ALONE:
            return [self.stop_after]
        if self.stop_after == "straight":
            return ["baseline", "engineer"]
        return STAGES[: STAGES.index(self.stop_after) + 1]

    @property
    def ceremony(self) -> bool:
        """Whether this goes through planning and approval."""
        return self.stop_after not in (*ALONE, "straight")

    def task_for(self, answer: str) -> str:
        if not self.task_template:
            return answer
        if "{what}" in self.task_template:
            return self.task_template.format(what=_fits(self.task_template, answer))
        return self.task_template


def _fits(template: str, answer: str) -> str:
    """What somebody typed, trimmed to sit inside the sentence around it.

    The templates are sentences with a hole in them - "Build {what}.
    Tests from the first commit" - and people type whole sentences into
    the hole. "Build a website for LUMI." came out as "Build Build a
    website for LUMI.. Tests from the first commit", which is the first
    thing every station read and the first thing the person saw back.

    Two trims, both only at the seam. The verb the template already
    supplies is dropped if they typed it again, and the full stop the
    template already supplies is dropped if they typed that too. Nothing
    else about what they wrote is touched.
    """
    said = (answer or "").strip()
    if not said:
        return said

    before, _, after = template.partition("{what}")
    lead = re.search(r"(\w+)\s+$", before)
    if lead:
        word = lead.group(1)
        head = re.match(rf"{re.escape(word)}\s+(?=\S)", said, re.IGNORECASE)
        if head:
            said = said[head.end() :]

    if after[:1] in ".!?" and said[-1:] in ".!?":
        said = said[:-1].rstrip()
    return said


BUILT_IN = [
    Command(
        name="/ask",
        summary="A question about this project. Nothing is changed.",
        asks="what you want to know",
        task_template="{what}",
        stop_after="ask",
    ),
    Command(
        name="/fix",
        summary="One small change, straight away. No plan, no approval.",
        asks="what to change",
        task_template="{what}",
        stop_after="straight",
    ),
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
        name="/review",
        summary="Read what has changed and say what is wrong. Nothing is changed.",
        task_template=(
            "Review what has changed in this repository and report what is "
            "wrong with it. Change nothing."
        ),
        stop_after="review",
    ),
    Command(
        name="/qa",
        summary=(
            "Run it, look at it, and report what is broken. Add what it is "
            "supposed to do and that is checked too. Nothing is changed."
        ),
        # No `asks`: on its own this measures, and `asks` makes an
        # argument compulsory - so the most natural thing anybody types,
        # `/qa` and nothing else, came back as a refusal.
        task_template="{what}",
        stop_after="qa",
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
    # Any whitespace, not only a space. A brief typed as `/new` and then
    # a newline and then twenty lines - which is how anybody writes one -
    # left the whole thing as the command name and came back "unknown
    # command. Type / to see the list."
    head, rest = (text.split(None, 1) + [""])[:2]
    for command in commands:
        if command.name == head:
            return command, rest.strip()
    return None, text


def suggest(prefix: str, commands: list[Command]) -> list[Command]:
    prefix = prefix.strip().lower()
    if not prefix.startswith("/"):
        return []
    return [c for c in commands if c.name.startswith(prefix)]
