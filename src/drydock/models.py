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
    has_tests: bool = False

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
    # The same item said once for somebody who is not going to open the
    # files. A plan nobody outside the work can read is a plan that gets
    # approved without being read, which is the opposite of what asking for
    # approval is for.
    plain: str = ""
    rationale: str
    files: list[str]
    verify_with: str = Field(description="build or tests")
    needs: list[int] = Field(
        default_factory=list,
        description=(
            "The items this one cannot be started before. Items that need "
            "nothing from each other are worked on at the same time, so an "
            "honest answer here is the difference between a run that takes "
            "twenty minutes and one that takes forty. An item that touches "
            "the same file as another, or that imports what another writes, "
            "needs it."
        ),
    )
    removes_tests: bool = Field(
        default=False,
        description=(
            "True only if this item is meant to delete tests - a duplicate "
            "suite being dropped, a module being removed. The inspector "
            "refuses an item that loses tests without saying so here, which "
            "is what makes losing them always a decision somebody wrote down."
        ),
    )
    # Decisions taken about this item after it was written. The engineer can
    # stop and ask when an item turns on something nobody decided, and the
    # planner answers - but the answer used to live for the length of one
    # attempt. The next attempt read the original item, made the same
    # discovery, and the reviewer refused it for not doing what the item
    # still said. So a settled question is written onto the item, and
    # everyone downstream judges it as settled.
    settled: list[str] = Field(default_factory=list, exclude=False)
    worth_looking_at: bool | None = Field(
        default=None,
        description=(
            "Whether somebody should look at the rendered page to judge this "
            "item. True for work whose whole point is what it looks like. "
            "False for scaffolding, configuration, data, a test command, a "
            "placeholder - anything whose success is a build passing rather "
            "than a page being right. Getting this wrong in either direction "
            "is expensive: a critic sent to judge a placeholder page refuses "
            "it for being a placeholder, and three attempts go on an item "
            "that was finished the first time."
        ),
    )

    def as_asked(self) -> str:
        """The item, including anything since decided about it."""
        said = f"{self.title}\n\nWhy it exists: {self.rationale}"
        if self.settled:
            said += "\n\nSince this was written, these questions about it "
            said += "have been put to whoever wrote it and answered. They are "
            said += "part of the item now and they win over anything above "
            said += "that disagrees with them:\n\n"
            said += "\n\n".join(f"- {s}" for s in self.settled)
        return said


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
    verified_commit: str | None = None
    tests_run: int = 0
    # Something true that was said against this item and did not stop it.
    # The critic's last word, when it was the only thing wrong: an item
    # that builds, holds its test count, comes through the inspector
    # clean and does what the item said is kept even if it looks wrong,
    # because the weakest of the four claims is not worth six items
    # nobody attempted - and it is written down, because it is still true.
    outstanding: str = ""
    # Everything true that was said about this item and did not stop it:
    # what the engineer noticed outside its scope, what the reviewer saw
    # in the diff, what the critic saw on the page. All three stations
    # produce these and all three were being dropped on the floor - the
    # reviewer reported that a failure path could hang a request for the
    # life of the process, and the sentence existed only in a CLI
    # transcript nobody reads. Each entry says who said it.
    noticed: list[str] = Field(default_factory=list)
