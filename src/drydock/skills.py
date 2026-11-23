"""Skills: packaged knowledge about one kind of work.

A skill is a directory with a SKILL.md in it, following the format Claude Code
and several other tools already read. The frontmatter says what the skill is
for and is cheap enough to load for all of them at once; the body says how to
do the work and is only read when the skill is actually chosen. That is the
whole of progressive disclosure, and it is why a hundred skills can be
installed without any of them costing anything until they are used.

What makes a skill here different from a prompt is that it speaks to four
different readers. The crew is not one agent with one instruction: the Analyst
needs to know what to look for, the Planner what order things have to happen
in, the Engineer where the traps are, and the verification what counts as
proof. A skill carries a section for each, and an agent is only handed its own.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

SECTIONS = ("survey", "design", "plan", "engineer", "verify")

# Which of those a station actually asks for. `survey` and `verify` are
# understood, so a skill written for the four-station path still loads -
# but nothing reads them unless DRYDOCK_FOUR_STATIONS is set, and a
# section nobody reads is a section somebody wrote for nothing.
#
# Measured before this existed: greenfield's `## Verify` and three other
# skills' `## Survey` sections, 5,160 characters between them, delivered
# to no one. Nobody knew, because nothing said.
ASKED_FOR = ("design", "plan", "engineer")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    applies_to: tuple[str, ...] = ()
    command: str = ""
    task: str = ""
    asks: str = ""
    sections: dict[str, str] | None = None
    # Headings in the body that no station will ever be given, and why.
    # Kept rather than dropped: a section written and never delivered is
    # the quietest way for work to go missing, and this is how it is
    # said out loud. See `complaints`.
    unread: tuple[tuple[str, str], ...] = ()

    @property
    def loaded(self) -> bool:
        return self.sections is not None

    def guidance(self, role: str) -> str:
        """The part of this skill a given role is handed. Empty if it has none."""
        if not self.sections:
            return ""
        return self.sections.get(role, "").strip()

    def complaints(self) -> list[str]:
        """What about this skill will not reach anybody, said plainly."""
        return [f"{self.name}: `## {head}` {why}" for head, why in self.unread]

    def fits(self, language: str, build_tool: str) -> bool:
        if not self.applies_to:
            return True
        targets = {t.lower() for t in self.applies_to}
        return language.lower() in targets or build_tool.lower() in targets


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("a SKILL.md must start with YAML frontmatter")
    _, raw, body = text.split("---", 2)
    return yaml.safe_load(raw) or {}, body


def _split_sections(body: str) -> dict[str, str]:
    """Carve the body into the parts each role is given.

    Headings are matched loosely on purpose. A skill is written by a person,
    and refusing to load one because the heading says "## Engineer notes"
    instead of "## Engineer" would make the format hostile for no benefit.
    """
    found: dict[str, str] = {}
    unread: list[tuple[str, str]] = []
    chunks = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    for heading, content in zip(chunks[1::2], chunks[2::2], strict=False):
        key = heading.strip().lower()
        role = next((r for r in SECTIONS if key.startswith(r)), "")
        if not role:
            unread.append(
                (
                    heading.strip(),
                    (
                        "names no station, so none of it is read. Rename "
                        f"it to one of {', '.join(SECTIONS)}, or fold it "
                        f"into one that is ({len(content.strip())} "
                        "characters)."
                    ),
                )
            )
            continue
        if role not in ASKED_FOR:
            unread.append(
                (
                    heading.strip(),
                    (
                        "is only read on the four-station path, which is "
                        "off unless DRYDOCK_FOUR_STATIONS is set "
                        f"({len(content.strip())} characters)."
                    ),
                )
            )
        found[role] = content.strip()
    return found, unread


def discover(root: Path) -> list[Skill]:
    """Read the frontmatter of every installed skill, and nothing more."""
    skills = []
    for skill_file in sorted(root.glob("*/SKILL.md")):
        meta, _ = _split_frontmatter(skill_file.read_text())
        skills.append(
            Skill(
                name=meta.get("name", skill_file.parent.name),
                description=meta.get("description", ""),
                path=skill_file.parent,
                applies_to=tuple(meta.get("applies_to", [])),
                # A skill declares the command that invokes it. Keeping the
                # two together means installing a skill installs its command,
                # and nothing has to be registered in a second place.
                command=meta.get("command", ""),
                task=meta.get("task", ""),
                asks=meta.get("asks", ""),
            )
        )
    return skills


def load(skill: Skill) -> Skill:
    """Read the body. Called once a skill has actually been chosen.

    Anything in it that no station will be given is recorded and said on
    the way past, because a section written and never delivered is the
    quietest way for work to go missing. Four skills had one; nobody
    knew.
    """
    _, body = _split_frontmatter((skill.path / "SKILL.md").read_text())
    sections, unread = _split_sections(body)
    for said in Skill(
        name=skill.name, description="", path=skill.path, unread=tuple(unread)
    ).complaints():
        print(f"skill: {said}", file=sys.stderr)
    return Skill(
        name=skill.name,
        description=skill.description,
        path=skill.path,
        applies_to=skill.applies_to,
        command=skill.command,
        task=skill.task,
        asks=skill.asks,
        sections=sections,
        unread=tuple(unread),
    )


def briefing(skills: list[Skill], *roles: str) -> str:
    """Everything the chosen skills have to say to one or more roles.

    More than one because a station can do more than one job. `start.py`
    reads, directs and plans in a single call, so it needs the design
    section as well as the plan one - and asking twice would send the
    preamble below twice, which is the larger half of a short briefing.
    """
    parts = [
        f"From the skill '{s.name}':\n\n{s.guidance(role)}"
        for role in roles
        for s in skills
        if s.guidance(role)
    ]
    if not parts:
        return ""
    return (
        "\n\nThe following is packaged knowledge about this kind of work. It "
        "was written by someone who has done it before and it is more "
        "reliable than what you would reconstruct from the repository "
        "alone.\n\n"
        # The ranking, said out loud. A skill used to be ranked above
        # everything except the repository, which put a document written
        # months ago for nobody in particular above the sentence somebody
        # typed this morning. The greenfield skill told the planner to
        # make a skeleton item and one item per feature, and to give a
        # restaurant a live open-or-closed line; the request said none of
        # it, and a run built all of it.
        "**Where it disagrees with something, here is what wins.** What "
        "the person asked for comes first and is never overridden - not "
        "by this, not by anything. Then the instructions above this "
        "block, which are how this crew works and what it may not do. "
        "Then what you actually read in the repository, which is a fact "
        "about this job where a skill is a generalisation about jobs "
        "like it. This block is last.\n\n"
        "So a skill may tell you how to do something well. It may not "
        "add an item, a feature or a requirement that the person did not "
        "ask for, and it may not change how the work is cut up when the "
        "instructions above have already said. Where it disagrees with "
        "any of them, follow them and say in your answer that the two "
        "disagreed.\n\n" + "\n\n".join(parts)
    )
