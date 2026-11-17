"""The shapes that move between agents.

Every agent hands the next one a typed object rather than prose. It is slower
to write and it is the reason a bad step can be pointed at: when the plan is a
list of items with files and a verification command attached, a failure belongs
to one item, not to a paragraph.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Check(BaseModel):
    """One command the repository is judged by."""

    name: str
    command: str
    passed: bool
    seconds: float
    detail: str = ""


class Baseline(BaseModel):
    """The state of the repository before anything is touched.

    Nothing can be called a regression without this. The first thing the crew
    does is run the build and the tests unchanged, because a suite that was
    already red is not evidence of anything afterwards.
    """

    builds: bool
    tests_run: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    checks: list[Check] = Field(default_factory=list)

    @property
    def green(self) -> bool:
        return self.builds and self.tests_failed == 0


class Inventory(BaseModel):
    """What the Analyst found by running commands, not by guessing."""

    build_tool: str
    language: str
    test_command: str
    build_command: str
    source_files: int
    test_files: int
    findings: list[str] = Field(
        default_factory=list,
        description="Facts gathered from the repository that bear on the task.",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Places the task is likely to break something.",
    )


class Item(BaseModel):
    """One unit of work, small enough to verify on its own."""

    id: int
    title: str
    rationale: str
    files: list[str]
    verify_with: str = Field(description="build or tests")


class Plan(BaseModel):
    summary: str
    items: list[Item]


class Outcome(str, Enum):
    DONE = "done"
    REVERTED = "reverted"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class ItemResult(BaseModel):
    item: Item
    outcome: Outcome
    attempts: int = 1
    files_changed: list[str] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    note: str = ""
    commit: str | None = None
