"""Who is in the room, and what each of them is allowed to do.

Kept in one place because it was in three: the office draws them, the
session names them when it skips one, and the slash menu had never heard of
them at all. Three lists of the same nine things is three lists that drift.

What each entry says is deliberately narrow. A station is defined by what it
decides and whether it can refuse, not by a personality.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    name: str
    does: str
    # What it is given, and what it hands on. The pairs are the pipeline.
    reads: str
    says: str
    # Whether it can send an item back. Three can, and that is the whole
    # design: the thing that writes the code is not the thing that decides
    # the code may stay.
    can_refuse: bool
    # Whether a model is involved at all. Two of them are arithmetic, which
    # is why they cannot be argued with.
    is_code: bool
    when: str


CREW = (
    Station(
        "Analyst",
        "reads the repository and reports what bears on the job",
        "the repository, and what was learned here before",
        "findings and risks",
        can_refuse=False,
        is_code=False,
        when="when there is something here to read",
    ),
    Station(
        "Architect",
        "decides what it is built with",
        "the task, and an empty folder",
        "a stack, a run command, a test command that fails on an empty suite",
        can_refuse=False,
        is_code=False,
        when="only when the repository is empty",
    ),
    Station(
        "Designer",
        "decides how it looks, for this business and not in general",
        "the task",
        "a palette, a type scale, a composition, a mark it draws itself",
        can_refuse=False,
        is_code=False,
        when="when somebody is going to look at the result",
    ),
    Station(
        "Planner",
        "turns all of that into items that can be done one at a time",
        "the survey, the shape and the direction",
        "an ordered plan, each item saying what it needs",
        can_refuse=False,
        is_code=False,
        when="on anything that is not a question or a one-line change",
    ),
    Station(
        "Engineer",
        "makes one change, and nothing outside it",
        "one item, the direction, and what the last attempt got wrong",
        "a change on disk and a report of what it did",
        can_refuse=False,
        is_code=False,
        when="once per item",
    ),
    Station(
        "Verifier",
        "builds it and runs the suite against the count from before",
        "the working tree",
        "a number, and whether it may stay",
        can_refuse=True,
        is_code=True,
        when="after every item",
    ),
    Station(
        "Inspector",
        "reads the diff for what a green suite cannot see",
        "the diff, and the files it added",
        "removed tests, silenced tests, lost assertions, secrets, "
        "dependencies committed, an image that is not what it claims",
        can_refuse=True,
        is_code=True,
        when="after every item",
    ),
    Station(
        "Reviewer",
        "asks whether the change did the item, and only the item",
        "the diff and the item it was given",
        "a verdict, and anything true but outside the item",
        can_refuse=True,
        is_code=False,
        when="after every item",
    ),
    Station(
        "Critic",
        "looks at the rendered page against the direction",
        "the page as an image, at phone and desktop width",
        "a verdict on what is actually on the screen",
        can_refuse=True,
        is_code=False,
        when="after an item that changed what somebody sees",
    ),
)


def as_rows() -> list[dict]:
    return [
        {
            "name": s.name,
            "does": s.does,
            "reads": s.reads,
            "says": s.says,
            "can_refuse": s.can_refuse,
            "is_code": s.is_code,
            "when": s.when,
        }
        for s in CREW
    ]
